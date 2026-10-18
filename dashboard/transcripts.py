"""Read Claude Code session transcripts (append-only JSONL, possibly mid-write)."""
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TAIL_BYTES = 512 * 1024
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


def iter_records(path: Path, tail_bytes: int | None = None) -> Iterator[dict]:
    """Yield JSON records, skipping malformed lines (e.g. a half-written last line)."""
    with path.open("rb") as f:
        if tail_bytes is not None:
            size = f.seek(0, 2)
            f.seek(max(0, size - tail_bytes))
            if size > tail_bytes:
                f.readline()  # drop the partial first line
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


def summarize(path: Path) -> SessionSummary:
    summary = SessionSummary(0, None, "", path.stat().st_mtime)
    for rec in iter_records(path, TAIL_BYTES):
        if rec.get("timestamp"):
            summary.last_activity = parse_ts(rec["timestamp"])
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message") or {}
        if msg.get("usage") and not rec.get("isApiErrorMessage"):
            summary.context_tokens = context_tokens(msg["usage"])
            summary.model = msg.get("model")
        content = msg.get("content")
        for block in content if isinstance(content, list) else []:
            action = describe_block(block)
            if action:
                summary.last_action = action
    return summary
