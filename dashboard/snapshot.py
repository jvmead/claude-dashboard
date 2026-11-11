"""Assemble everything the page shows into one JSON-able dict."""
import os
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from dashboard.discovery import DiscoveryError, LiveSession
from dashboard.install import is_installed
from dashboard.jobs import load_jobs
from dashboard.status import SORT_ORDER, classify
from dashboard.subagents import SubagentNode, is_specialist, load_subagents, max_depth, outstanding, running, walk
from dashboard.transcripts import find_transcript, iter_records, scan
from dashboard.usage import estimate, file_records

CONTEXT_LIMIT = int(os.environ.get("CLAUDE_CONTEXT_LIMIT", 200_000))
TIMELINE_S = 20 * 60
SEGMENT_GAP_S = 60


def hook_log(claude_dir: Path) -> Path:
    return claude_dir / "dashboard" / "events.jsonl"


def _is_prompt(e: dict) -> bool:
    event = e.get("hook_event_name")
    return event == "PermissionRequest" or (event == "Notification"
                                            and e.get("notification_type") == "permission_prompt")


def pending_approvals(claude_dir: Path) -> set[str]:
    """Sessions with an unanswered permission prompt: the last hook event logged for some
    (session, agent) pair is a prompt. Keyed per agent so a background subagent's tool
    calls don't answer the parent's prompt. Log order is arrival order.

    ponytail: parallel tool calls in one turn can clear a prompt early (a sibling's
    PostToolUse lands while it's open); matching on tool_use_id would fix that."""
    last: dict[tuple[str, str | None], bool] = {}
    path = hook_log(claude_dir)
    if not path.exists():
        return set()
    for line in iter_records(path):
        e = line.get("e")
        if not isinstance(e, dict):
            continue
        if e.get("hook_event_name") == "Notification" and not _is_prompt(e):
            continue  # idle and other notifications answer nothing
        last[(e.get("session_id", ""), e.get("agent_id"))] = _is_prompt(e)
    return {sid for (sid, _), open_ in last.items() if open_}


def _segments(stamps: list[float]) -> list[list[float]]:
    """Group activity timestamps into busy spans, splitting on gaps > SEGMENT_GAP_S."""
    spans: list[list[float]] = []
    for t in sorted(stamps):
        if spans and t - spans[-1][1] <= SEGMENT_GAP_S:
            spans[-1][1] = t
        else:
            spans.append([t, t])
    return spans


def _files(transcript: Path) -> list[Path]:
    return [transcript, *(transcript.with_suffix("") / "subagents").glob("agent-*.jsonl")]


def _tokens_since(files: list[Path], since: float) -> float:
    total = 0.0
    for f in files:
        try:
            st = f.stat()
        except OSError:  # vanished since the glob
            continue
        records, _ = file_records(f, st.st_mtime_ns, st.st_size)
        total += sum(w for t, w, _ in records if t >= since)
    return total


def _node_dict(n: SubagentNode, since: float) -> dict:
    d = asdict(n)
    d["specialist"] = is_specialist(n.agent_type)
    d["running"] = running(n, since)
    d["children"] = [_node_dict(c, since) for c in n.children]
    return d


def _base_row(s: LiveSession, now: float) -> dict:
    return {"session_id": s.session_id, "name": s.name, "cwd": s.cwd, "age_s": now - s.started,
           "busy": s.busy, "last_action": "no transcript yet", "context_tokens": 0, "context_pct": 0.0,
           "model": None, "idle_s": 0.0, "outstanding": 0, "total_subagents": 0, "max_depth": 0,
           "specialists": 0, "generals": 0, "tokens_last_hour": 0.0, "subagents": [],
           "parent_busy_segments": []}


def session_row(claude_dir: Path, s: LiveSession, pending: set[str], now: float) -> dict:
    row = _base_row(s, now)
    transcript = find_transcript(claude_dir, s.session_id)
    if transcript is None:
        row["state"] = classify(s.busy, 0, 0, s.session_id in pending).value
        return row
    summary, stamps = scan(transcript)
    roots = load_subagents(transcript)
    nodes = list(walk(roots))
    files = _files(transcript)
    row.update(
        last_action=summary.last_action or "—",
        context_tokens=summary.context_tokens,
        context_pct=summary.context_tokens / CONTEXT_LIMIT,
        model=summary.model,
        idle_s=max(0.0, now - summary.last_activity),
        outstanding=outstanding(roots, s.started),
        total_subagents=len(nodes),
        max_depth=max_depth(roots),
        specialists=sum(is_specialist(n.agent_type) for n in nodes),
        generals=sum(not is_specialist(n.agent_type) for n in nodes),
        tokens_last_hour=_tokens_since(files, now - 3600),
        subagents=[_node_dict(n, s.started) for n in roots],
        parent_busy_segments=_segments([t for t in stamps if t >= now - TIMELINE_S]),
    )
    row["state"] = classify(s.busy, row["outstanding"], row["idle_s"], s.session_id in pending).value
    return row


def error_text(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"


def _safe_row(claude_dir: Path, s: LiveSession, pending: set[str], now: float) -> dict:
    """One unreadable session degrades to a bare row instead of failing the snapshot."""
    try:
        return session_row(claude_dir, s, pending, now)
    except Exception as e:  # shown on the row, not swallowed
        row = _base_row(s, now)
        row.update(last_action=f"can't read: {error_text(e)}"[:120],
                   state=classify(s.busy, 0, 0, s.session_id in pending).value)
        return row


def _safe_estimate(claude_dir: Path, now: float, ceiling_cache: Path) -> dict:
    try:
        return estimate(claude_dir, now, ceiling_cache)
    except Exception as e:  # shown in the strip, not swallowed
        return {"error": error_text(e)}


def build_snapshot(claude_dir: Path, sessions_fn: Callable[[], list[LiveSession]], now: float,
                   ceiling_cache: Path, log_dir: Path | None = None) -> dict:
    snap = {"now": now, "error": None, "sessions": [], "context_limit": CONTEXT_LIMIT,
            "hook_installed": is_installed(claude_dir / "settings.json"),
            "usage": _safe_estimate(claude_dir, now, ceiling_cache),
            "jobs": [asdict(j) for j in load_jobs(log_dir, now)]}
    try:
        sessions = sessions_fn()
    except DiscoveryError as e:
        snap["error"] = str(e)
        return snap
    pending = pending_approvals(claude_dir)
    rows = [_safe_row(claude_dir, s, pending, now) for s in sessions]
    order = {state.value: i for i, state in enumerate(SORT_ORDER)}
    snap["sessions"] = sorted(rows, key=lambda r: (order[r["state"]], r["idle_s"]))
    return snap
