import json
import socket

from dashboard import __main__ as cli


def test_open_when_already_running_just_opens_tab(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        cli.main(["--port", str(port), "--claude-dir", str(tmp_path), "--open"])  # must return, not raise
    assert opened == [f"http://127.0.0.1:{port}"]


def test_json_prints_one_snapshot_and_exits(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "list_sessions", lambda: [])
    cli.main(["--claude-dir", str(tmp_path), "--json"])  # must return, not serve
    snap = json.loads(capsys.readouterr().out)
    assert snap["sessions"] == [] and snap["error"] is None and snap["usage"] is None
