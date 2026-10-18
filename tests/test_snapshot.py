import json
import os

from dashboard.discovery import DiscoveryError, LiveSession
from dashboard.snapshot import build_snapshot, read_prompts
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
                                        "spawnDepth": 1, "finished": False})
    [row] = snap(claude_dir, [live("s1")], tmp_path)["sessions"]
    assert row["state"] == "waiting" and row["outstanding"] == 1 and row["specialists"] == 1
    assert row["subagents"][0]["description"] == "do x"


def write_hook_log(claude_dir, *events):
    d = claude_dir.root / "dashboard"
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text("".join(json.dumps({"ts": ts, "e": e}) + "\n" for ts, e in events))


def test_read_prompts(claude_dir):
    write_hook_log(claude_dir,
                   (10, {"hook_event_name": "Notification", "notification_type": "permission_prompt",
                         "session_id": "s1"}),
                   (20, {"hook_event_name": "Notification", "notification_type": "idle_prompt",
                         "session_id": "s1"}),
                   (30, {"hook_event_name": "PermissionRequest", "session_id": "s2"}))
    assert read_prompts(claude_dir.root) == {"s1": 10, "s2": 30}


def test_approval_from_hook_log(claude_dir, tmp_path):
    p = claude_dir.add_session("s1", [assistant(iso(NOW - 120), tool=("Bash", {"command": "rm -rf build"}))])
    os.utime(p, (NOW - 100, NOW - 100))
    write_hook_log(claude_dir, (NOW - 90, {"hook_event_name": "PermissionRequest", "session_id": "s1"}))
    [row] = snap(claude_dir, [live("s1", busy=True)], tmp_path)["sessions"]
    assert row["state"] == "approval" and row["last_action"] == "Bash: rm -rf build"


def test_hook_installed_reads_settings(claude_dir, tmp_path):
    from dashboard.install import install
    assert snap(claude_dir, [], tmp_path)["hook_installed"] is False
    install(claude_dir.root / "settings.json")
    assert snap(claude_dir, [], tmp_path)["hook_installed"] is True
