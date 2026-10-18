"""Assemble everything the page shows into one JSON-able dict."""
import json
import os
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from dashboard.discovery import DiscoveryError, LiveSession
from dashboard.status import SORT_ORDER, approval_pending, classify
from dashboard.subagents import SubagentNode, is_specialist, load_subagents, max_depth, outstanding, walk
from dashboard.transcripts import TAIL_BYTES, find_transcript, iter_records, parse_ts, summarize
from dashboard.usage import file_records, estimate

CONTEXT_LIMIT = int(os.environ.get("CLAUDE_CONTEXT_LIMIT", 200_000))
TIMELINE_S = 20 * 60
SEGMENT_GAP_S = 60


def hook_log(claude_dir: Path) -> Path:
    return claude_dir / "dashboard" / "events.jsonl"


def read_prompts(claude_dir: Path) -> dict[str, float]:
    """Last permission-prompt time per session, from the hook log."""
    prompts: dict[str, float] = {}
    path = hook_log(claude_dir)
    if not path.exists():
        return prompts
    for line in iter_records(path):
        e = line.get("e") or {}
        event = e.get("hook_event_name")
        if event == "PermissionRequest" or (event == "Notification"
                                            and e.get("notification_type") == "permission_prompt"):
            prompts[e.get("session_id", "")] = line.get("ts", 0)
    return prompts


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
        st = f.stat()
        records, _ = file_records(f, st.st_mtime_ns, st.st_size)
        total += sum(w for t, w, _ in records if t >= since)
    return total


def _node_dict(n: SubagentNode) -> dict:
    d = asdict(n)
    d["specialist"] = is_specialist(n.agent_type)
    d["children"] = [_node_dict(c) for c in n.children]
    return d


def session_row(claude_dir: Path, s: LiveSession, prompts: dict[str, float], now: float) -> dict:
    row = {"session_id": s.session_id, "name": s.name, "cwd": s.cwd, "age_s": now - s.started,
           "busy": s.busy, "last_action": "no transcript yet", "context_tokens": 0, "context_pct": 0.0,
           "model": None, "idle_s": 0.0, "outstanding": 0, "total_subagents": 0, "max_depth": 0,
           "specialists": 0, "generals": 0, "tokens_last_hour": 0.0, "subagents": [],
           "parent_busy_segments": []}
    transcript = find_transcript(claude_dir, s.session_id)
    if transcript is None:
        row["state"] = classify(s.busy, 0, 0, False).value
        return row
    summary = summarize(transcript)
    roots = load_subagents(transcript)
    nodes = list(walk(roots))
    files = _files(transcript)
    last_write = max(f.stat().st_mtime for f in files)
    stamps = [parse_ts(r["timestamp"]) for r in iter_records(transcript, TAIL_BYTES) if r.get("timestamp")]
    row.update(
        last_action=summary.last_action or "—",
        context_tokens=summary.context_tokens,
        context_pct=summary.context_tokens / CONTEXT_LIMIT,
        model=summary.model,
        idle_s=max(0.0, now - summary.last_activity),
        outstanding=outstanding(roots),
        total_subagents=len(nodes),
        max_depth=max_depth(roots),
        specialists=sum(is_specialist(n.agent_type) for n in nodes),
        generals=sum(not is_specialist(n.agent_type) for n in nodes),
        tokens_last_hour=_tokens_since(files, now - 3600),
        subagents=[_node_dict(n) for n in roots],
        parent_busy_segments=_segments([t for t in stamps if t >= now - TIMELINE_S]),
    )
    row["state"] = classify(s.busy, row["outstanding"], row["idle_s"],
                            approval_pending(prompts.get(s.session_id), last_write)).value
    return row


def build_snapshot(claude_dir: Path, sessions_fn: Callable[[], list[LiveSession]], now: float,
                   ceiling_cache: Path) -> dict:
    snap = {"now": now, "error": None, "sessions": [], "context_limit": CONTEXT_LIMIT,
            "hook_installed": hook_log(claude_dir).exists(),
            "usage": estimate(claude_dir, now, ceiling_cache)}
    try:
        sessions = sessions_fn()
    except DiscoveryError as e:
        snap["error"] = str(e)
        return snap
    prompts = read_prompts(claude_dir)
    rows = [session_row(claude_dir, s, prompts, now) for s in sessions]
    order = {state.value: i for i, state in enumerate(SORT_ORDER)}
    snap["sessions"] = sorted(rows, key=lambda r: (order[r["state"]], r["idle_s"]))
    return snap
