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


def test_multiline_action_is_collapsed(claude_dir):
    p = claude_dir.add_session("s1", [assistant("2026-10-18T10:00:00Z",
                                                tool=("Bash", {"command": "cd x &&\n  pytest"}))])
    assert summarize(p).last_action == "Bash: cd x && pytest"


def test_incremental_scan_sees_appends_and_waits_for_complete_lines(claude_dir):
    import json

    from dashboard.transcripts import scan
    p = claude_dir.add_session("s1", [assistant("2026-10-18T10:00:00Z", text="one")])
    summary, stamps = scan(p)
    assert summary.last_action == "one" and len(stamps) == 1
    line = json.dumps(assistant("2026-10-18T10:05:00Z", text="two"))
    with p.open("a") as f:
        f.write(line[:20])
    assert scan(p)[0].last_action == "one"
    with p.open("a") as f:
        f.write(line[20:] + "\n")
    summary, stamps = scan(p)
    assert summary.last_action == "two" and len(stamps) == 2


def test_whole_history_not_just_tail(claude_dir):
    from dashboard.transcripts import scan
    blob = {"type": "api-request-blob", "timestamp": "2026-10-18T10:00:30Z", "body": "x" * 600_000}
    p = claude_dir.add_session("s1", [assistant("2026-10-18T10:00:00Z", text="early"), blob])
    assert scan(p)[1][0] == 1792317600.0


def test_title_latest_ai_title_and_rename_kept_apart(claude_dir):
    p = claude_dir.add_session("s1", [{"type": "ai-title", "aiTitle": "first guess"},
                                      {"type": "ai-title", "aiTitle": "Model eval reruns"}])
    s = summarize(p)
    assert (s.title, s.custom_title) == ("Model eval reruns", None)
    p = claude_dir.add_session("s2", [{"type": "custom-title", "customTitle": "paper draft"},
                                      {"type": "ai-title", "aiTitle": "later ai title"}])
    s = summarize(p)
    assert (s.title, s.custom_title) == ("later ai title", "paper draft")


def test_kickoff_tag_is_first_kickoff_args_line(claude_dir):
    def user(text):
        return {"type": "user", "message": {"role": "user", "content": text}}
    kick = ("<command-message>kickoff</command-message>\n<command-name>/kickoff</command-name>\n"
            "<command-args>forecasting  eval 12\nSecond step of the plan</command-args>")
    p = claude_dir.add_session("s1", [user("hello"), user(kick), user(kick.replace("12", "99"))])
    assert summarize(p).kickoff == "eval 12 · forecasting"
    assert summarize(claude_dir.add_session("s2", [user("no kickoff")])).kickoff is None
