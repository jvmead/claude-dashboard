import json
import subprocess

from dashboard.install import HOOK_CMD, install, uninstall

OTHER = {"matcher": "*", "hooks": [{"type": "command", "command": "echo other"}]}


def settings(tmp_path, data):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(data))
    return p


def commands(p, event):
    return [h["command"] for e in json.loads(p.read_text())["hooks"].get(event, []) for h in e["hooks"]]


def test_install_is_idempotent(tmp_path):
    p = settings(tmp_path, {"model": "opus", "hooks": {"Notification": [OTHER]}})
    install(p)
    install(p)
    assert commands(p, "Notification") == ["echo other", HOOK_CMD]
    for event in ("PermissionRequest", "PostToolUse", "Stop", "SubagentStop", "UserPromptSubmit"):
        assert commands(p, event) == [HOOK_CMD]
    assert "matcher" not in json.loads(p.read_text())["hooks"]["Stop"][0]
    assert json.loads(p.read_text())["model"] == "opus"


def test_install_without_hooks_key(tmp_path):
    p = settings(tmp_path, {})
    install(p)
    assert commands(p, "PermissionRequest") == [HOOK_CMD]


def test_uninstall_leaves_other_hooks(tmp_path):
    p = settings(tmp_path, {"hooks": {"Notification": [OTHER]}})
    install(p)
    uninstall(p)
    hooks = json.loads(p.read_text())["hooks"]
    assert hooks == {"Notification": [OTHER]}


def test_hook_command_writes_one_wrapped_line(tmp_path):
    payload = {"hook_event_name": "PermissionRequest", "session_id": "s1", "tool_input": {"command": "a\nb"}}
    pretty = json.dumps(payload, indent=2)  # newlines between tokens must not split the record
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    for _ in range(2):
        r = subprocess.run(["sh", "-c", HOOK_CMD], input=pretty, text=True, env=env, capture_output=True)
        assert r.returncode == 0 and r.stdout == ""
    lines = (tmp_path / ".claude" / "dashboard" / "events.jsonl").read_text().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["e"] == payload and isinstance(rec["ts"], float)  # sub-second: prompts land ms after writes


def test_install_keeps_non_ascii_text_as_is(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"note": "a — b"}')
    install(p)
    assert "a — b" in p.read_text()
