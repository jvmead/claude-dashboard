"""Read Claude Code session transcripts (append-only JSONL, possibly mid-write)."""
import json
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

ACTION_CHARS = 60
# Tool input keys worth showing, in order of preference.
ACTION_KEYS = ("command", "file_path", "description", "pattern", "url", "prompt")


@dataclass
class SessionSummary:
    context_tokens: int
    model: str | None
    last_action: str
    last_activity: float


def parse_ts(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


def iter_records(path: Path) -> Iterator[dict]:
    """Yield JSON records, skipping malformed lines (e.g. a half-written last line)."""
    with path.open("rb") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield rec


def find_transcript(claude_dir: Path, session_id: str) -> Path | None:
    return next((claude_dir / "projects").glob(f"*/{session_id}.jsonl"), None)


def context_tokens(usage: dict) -> int:
    return sum(usage.get(k) or 0 for k in
               ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


def describe_block(block: dict) -> str | None:
    if block.get("type") == "tool_use":
        inp = block.get("input") or {}
        detail = " ".join(next((str(inp[k]) for k in ACTION_KEYS if inp.get(k)), "").split())
        return f"{block.get('name')}: {detail}".rstrip(": ")[:ACTION_CHARS]
    if block.get("type") == "text" and block.get("text", "").strip():
        return block["text"].strip().splitlines()[0][:ACTION_CHARS]
    return None


# path -> (bytes consumed, running summary, activity timestamps). Transcripts are append-only,
# so each refresh only parses what was written since the last one.
_scanned: dict[Path, tuple[int, SessionSummary, list[float]]] = {}


def _apply(rec: dict, summary: SessionSummary, stamps: list[float]) -> None:
    if rec.get("timestamp"):
        summary.last_activity = parse_ts(rec["timestamp"])
        stamps.append(summary.last_activity)
    if rec.get("type") != "assistant":
        return
    msg = rec.get("message") or {}
    if msg.get("usage") and not rec.get("isApiErrorMessage"):
        summary.context_tokens = context_tokens(msg["usage"])
        summary.model = msg.get("model")
    content = msg.get("content")
    for block in content if isinstance(content, list) else []:
        action = describe_block(block)
        if action:
            summary.last_action = action


def scan(path: Path) -> tuple[SessionSummary, tuple[float, ...]]:
    """Summary plus all activity timestamps, reading only complete lines added since last call."""
    size = path.stat().st_size
    offset, summary, stamps = _scanned.get(path, (0, None, None))
    if summary is None or size < offset:  # first sight, or file was replaced
        offset, summary, stamps = 0, SessionSummary(0, None, "", path.stat().st_mtime), []
    with path.open("rb") as f:
        f.seek(offset)
        data = f.read(size - offset)
    complete = data[: data.rfind(b"\n") + 1]  # a half-written last line waits for next time
    for line in complete.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            _apply(rec, summary, stamps)
    _scanned[path] = (offset + len(complete), summary, stamps)
    return replace(summary), tuple(stamps)


def summarize(path: Path) -> SessionSummary:
    return scan(path)[0]
