import json
from pathlib import Path

import pytest


def assistant(ts: str, *, tool: tuple[str, dict] | None = None, text: str | None = None,
              usage: dict | None = None, model: str = "claude-opus-5-5", msg_id: str = "m1") -> dict:
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool is not None:
        content.append({"type": "tool_use", "name": tool[0], "input": tool[1]})
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": msg_id, "model": model, "content": content,
                        "usage": usage or {"input_tokens": 1, "cache_creation_input_tokens": 0,
                                           "cache_read_input_tokens": 0, "output_tokens": 1}}}


class ClaudeDir:
    """Builds a fake ~/.claude tree for tests."""

    def __init__(self, root: Path):
        self.root = root
        self.project = root / "projects" / "-home-x-proj"
        self.project.mkdir(parents=True)

    def add_session(self, sid: str, records: list[dict]) -> Path:
        path = self.project / f"{sid}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
        return path

    def add_subagent(self, sid: str, aid: str, meta: dict, records: list[dict] | None = None) -> None:
        d = self.project / sid / "subagents"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"agent-{aid}.meta.json").write_text(json.dumps(meta))
        if records is not None:
            (d / f"agent-{aid}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))


@pytest.fixture
def claude_dir(tmp_path: Path) -> ClaudeDir:
    return ClaudeDir(tmp_path / ".claude")
