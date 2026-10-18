import json
import os

from dashboard.discovery import DiscoveryError, LiveSession
from dashboard.snapshot import build_snapshot, pending_approvals
from tests.conftest import assistant
from tests.test_usage import iso

NOW = 1_800_000_000


def live(sid, busy=False):
    return LiveSession(pid=1, cwd="/p", session_id=sid, name=sid, busy=busy, started=NOW - 3600)


def snap(claude_dir, sessions, tmp_path):
    def fn():
        if isinstance(sessions, Exception):
            raise sessions
        return sessions
    return build_snapshot(claude_dir.root, fn, NOW, tmp_path / "c.json")


def test_discovery_failure_reported(claude_dir, tmp_path):
    s = snap(claude_dir, DiscoveryError("claude not found"), tmp_path)
    assert s["error"] == "claude not found" and s["sessions"] == []


def test_session_without_transcript(claude_dir, tmp_path):
    [row] = snap(claude_dir, [live("ghost", busy=True)], tmp_path)["sessions"]
    assert row["state"] == "working" and row["last_action"] == "no transcript yet"


def test_sorted_by_attention(claude_dir, tmp_path):
    claude_dir.add_session("parked", [assistant(iso(NOW - 7200), text="done")])
    claude_dir.add_session("turn", [assistant(iso(NOW - 60), text="Which DB?")])
    claude_dir.add_session("busy", [assistant(iso(NOW - 5), text="...")])
    rows = snap(claude_dir, [live("parked"), live("busy", busy=True), live("turn")], tmp_path)["sessions"]
    assert [(r["session_id"], r["state"]) for r in rows] == [
        ("turn", "your_turn"), ("busy", "working"), ("parked", "parked")]
    assert rows[0]["last_action"] == "Which DB?"


def test_waiting_on_background_subagent(claude_dir, tmp_path):
    claude_dir.add_session("s1", [assistant(iso(NOW - 60), text="spawned")])
    claude_dir.add_subagent("s1", "a", {"agentType": "python-pro", "description": "do x",
                                        "spawnDepth": 1, "finished": False},
                            [assistant(iso(NOW - 30), text="working")])
    [row] = snap(claude_dir, [live("s1")], tmp_path)["sessions"]
    assert row["state"] == "waiting" and row["outstanding"] == 1 and row["specialists"] == 1
    assert row["subagents"][0]["description"] == "do x"


def write_hook_log(claude_dir, *events):
    d = claude_dir.root / "dashboard"
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text("".join(json.dumps({"ts": ts, "e": e}) + "\n" for ts, e in events))


def prompt(sid, **extra):
    return {"hook_event_name": "PermissionRequest", "session_id": sid, **extra}


def test_pending_approvals(claude_dir):
    write_hook_log(claude_dir,
                   (1.0, prompt("answered")), (2.0, {"hook_event_name": "PostToolUse", "session_id": "answered"}),
                   (1.0, prompt("open")),
                   (1.0, {"hook_event_name": "Notification", "notification_type": "idle_prompt",
                          "session_id": "idle"}),
                   (1.0, {"hook_event_name": "Notification", "notification_type": "permission_prompt",
                          "session_id": "stopped"}), (2.0, {"hook_event_name": "Stop", "session_id": "stopped"}),
                   # a background subagent finishing a tool doesn't answer the parent's prompt
                   (1.0, prompt("bg")), (2.0, {"hook_event_name": "PostToolUse", "session_id": "bg",
                                               "agent_id": "a"}),
                   (1.0, prompt("sub", agent_id="a")), (2.0, {"hook_event_name": "SubagentStop",
                                                              "session_id": "sub", "agent_id": "a"}))
    assert pending_approvals(claude_dir.root) == {"open", "bg"}


def test_approval_survives_later_transcript_write(claude_dir, tmp_path):
    p = claude_dir.add_session("s1", [assistant(iso(NOW - 120), tool=("Bash", {"command": "rm -rf build"}))])
    write_hook_log(claude_dir, (NOW - 90.5, prompt("s1")))
    os.utime(p, (NOW - 90, NOW - 90))  # attachment write landing alongside the prompt
    [row] = snap(claude_dir, [live("s1", busy=True)], tmp_path)["sessions"]
    assert row["state"] == "approval" and row["last_action"] == "Bash: rm -rf build"


def test_hook_installed_reads_settings(claude_dir, tmp_path):
    from dashboard.install import install
    assert snap(claude_dir, [], tmp_path)["hook_installed"] is False
    install(claude_dir.root / "settings.json")
    assert snap(claude_dir, [], tmp_path)["hook_installed"] is True


def test_malformed_record_skipped(claude_dir, tmp_path):
    bad = assistant(iso(NOW - 30), text="ok")
    p = claude_dir.add_session("s1", [assistant(iso(NOW - 60), text="first")])
    with p.open("a") as f:
        f.write(json.dumps({**bad, "timestamp": "garbage"}) + "\n")
    os.utime(p, (NOW - 30, NOW - 30))
    claude_dir.add_subagent("s1", "a", {"agentType": "x"}, [{**bad, "timestamp": 5}])
    s = snap(claude_dir, [live("s1")], tmp_path)
    assert s["sessions"][0]["last_action"] == "first" and s["usage"]["used"] > 0


def test_one_broken_session_keeps_the_rest(claude_dir, tmp_path, monkeypatch):
    import dashboard.snapshot as snapshot
    claude_dir.add_session("ok", [assistant(iso(NOW - 60), text="fine")])
    claude_dir.add_session("gone", [assistant(iso(NOW - 60), text="fine")])
    real = snapshot.scan

    def scan(path):
        if path.stem == "gone":
            raise FileNotFoundError(path)
        return real(path)
    monkeypatch.setattr(snapshot, "scan", scan)
    rows = {r["session_id"]: r for r in snap(claude_dir, [live("ok"), live("gone", busy=True)], tmp_path)["sessions"]}
    assert rows["ok"]["last_action"] == "fine"
    assert rows["gone"]["state"] == "working" and rows["gone"]["last_action"].startswith("can't read")


def test_usage_failure_keeps_sessions(claude_dir, tmp_path, monkeypatch):
    import dashboard.snapshot as snapshot

    def boom(*_):
        raise OSError("disk gone")
    monkeypatch.setattr(snapshot, "estimate", boom)
    s = snap(claude_dir, [live("ghost")], tmp_path)
    assert s["usage"] == {"error": "OSError: disk gone"} and len(s["sessions"]) == 1


def test_stale_unfinished_subagent_from_before_resume(claude_dir, tmp_path):
    claude_dir.add_session("s1", [assistant(iso(NOW - 60), text="resumed")])
    claude_dir.add_subagent("s1", "old", {"agentType": "Explore", "description": "old"},  # no "finished"
                            [assistant(iso(NOW - 7200), text="...")])  # live() started at NOW - 3600
    [row] = snap(claude_dir, [live("s1")], tmp_path)["sessions"]
    assert row["state"] == "your_turn" and row["outstanding"] == 0
    assert row["subagents"][0]["running"] is False
