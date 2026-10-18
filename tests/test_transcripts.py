from dashboard.transcripts import find_transcript, iter_records, summarize
from tests.conftest import assistant

USAGE = {"input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 5000,
         "output_tokens": 50}


def test_context_from_last_usage(claude_dir):
    p = claude_dir.add_session("s1", [assistant("2026-10-18T10:00:00Z"),
                                      assistant("2026-10-18T10:01:00Z", text="hi", usage=USAGE)])
    s = summarize(p)
    assert s.context_tokens == 5102
    assert s.model == "claude-opus-5-5"
    assert s.last_activity == 1792317660.0


def test_tool_use_action(claude_dir):
    p = claude_dir.add_session("s1", [assistant("2026-10-18T10:00:00Z", text="running",
                                                tool=("Bash", {"command": "pytest -q tests/"}))])
    assert summarize(p).last_action == "Bash: pytest -q tests/"


def test_text_action_is_first_line(claude_dir):
    p = claude_dir.add_session("s1", [assistant("2026-10-18T10:00:00Z", text="Which DB?\nmore")])
    assert summarize(p).last_action == "Which DB?"


def test_partial_last_line(claude_dir):
    p = claude_dir.add_session("s1", [assistant("2026-10-18T10:00:00Z", text="ok")])
    with p.open("a") as f:
        f.write('{"type": "assistant", "timest')
    assert [r["type"] for r in iter_records(p)] == ["assistant"]
    assert summarize(p).last_action == "ok"


def test_find_transcript(claude_dir):
    p = claude_dir.add_session("abc", [])
    assert find_transcript(claude_dir.root, "abc") == p
    assert find_transcript(claude_dir.root, "nope") is None
