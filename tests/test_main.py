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
