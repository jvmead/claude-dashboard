"""Subagent tree from the meta.json files Claude Code writes beside each session transcript."""
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dashboard.transcripts import iter_records, parse_ts

GENERALISTS = {"general-purpose", "Explore", "Plan", "claude"}


@dataclass
class SubagentNode:
    agent_id: str
    agent_type: str
    description: str
    parent_id: str | None
    depth: int
    background: bool
    finished: bool
    started: float
    last_activity: float
    tokens: int
    children: list["SubagentNode"] = field(default_factory=list)


def is_specialist(agent_type: str) -> bool:
    return agent_type not in GENERALISTS


@lru_cache(maxsize=1024)
def _transcript_stats(path: Path, _mtime_ns: int, _size: int) -> tuple[float, float, int]:
    """(first ts, last ts, tokens) for one agent transcript; cache keyed on file identity."""
    first = last = 0.0
    seen: dict[str, int] = {}
    for rec in iter_records(path):
        try:
            if rec.get("timestamp"):
                last = parse_ts(rec["timestamp"])
                first = first or last
            msg = rec.get("message") or {}
            if rec.get("type") == "assistant" and msg.get("usage"):
                u = msg["usage"]
                # Cache reads are excluded: they re-count the same context every turn.
                seen[msg.get("id", "")] = sum(u.get(k) or 0 for k in
                                              ("input_tokens", "cache_creation_input_tokens", "output_tokens"))
        except (ValueError, TypeError, AttributeError):  # malformed record: skip just it
            continue
    return first, last, sum(seen.values())


def transcript_stats(path: Path) -> tuple[float, float, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return _transcript_stats(path, st.st_mtime_ns, st.st_size)


def _node(meta_path: Path) -> SubagentNode | None:
    try:
        meta = json.loads(meta_path.read_text())
        mtime = meta_path.stat().st_mtime
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    agent_id = meta_path.name.removeprefix("agent-").removesuffix(".meta.json")
    first, last, tokens = transcript_stats(meta_path.with_name(f"agent-{agent_id}.jsonl")) or (mtime, mtime, 0)
    return SubagentNode(agent_id, meta.get("agentType", "?"), meta.get("description", ""),
                        meta.get("parentAgentId"), meta.get("spawnDepth", 1),
                        meta.get("requestShape") == "background", bool(meta.get("finished")),
                        first or mtime, last or mtime, tokens)


def load_subagents(transcript: Path) -> list[SubagentNode]:
    """Root subagents (spawned by the main session), children nested, ordered by start time."""
    sub_dir = transcript.with_suffix("") / "subagents"
    nodes = {n.agent_id: n for p in sub_dir.glob("agent-*.meta.json") if (n := _node(p))}
    roots = []
    for n in sorted(nodes.values(), key=lambda n: n.started):
        parent = nodes.get(n.parent_id) if n.parent_id else None
        (parent.children if parent else roots).append(n)
    return roots


def walk(nodes: list[SubagentNode]):
    for n in nodes:
        yield n
        yield from walk(n.children)


def running(n: SubagentNode, since: float) -> bool:
    """Unfinished and active since `since` (the session's start): meta.json files left by an
    earlier run of a resumed session often lack `finished` and would otherwise run forever."""
    return not n.finished and n.last_activity >= since


def outstanding(nodes: list[SubagentNode], since: float = 0.0) -> int:
    return sum(running(n, since) for n in walk(nodes))


def max_depth(nodes: list[SubagentNode]) -> int:
    return max((n.depth for n in walk(nodes)), default=0)
