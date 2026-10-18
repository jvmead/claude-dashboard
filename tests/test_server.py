import json
import threading
import urllib.error
import urllib.request

import pytest

from dashboard.discovery import LiveSession
from dashboard.server import make_server


@pytest.fixture
def base_url(claude_dir, tmp_path):
    sessions = [LiveSession(1, "/p", "s1", "proj", True, 0.0)]
    server = make_server(0, claude_dir.root, lambda: sessions, tmp_path / "c.json")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers["Content-Type"], r.read()


def test_api_state(base_url):
    status, ctype, body = get(base_url + "/api/state")
    assert status == 200 and ctype.startswith("application/json")
    assert json.loads(body)["sessions"][0]["session_id"] == "s1"


def test_index_and_assets(base_url):
    assert get(base_url + "/")[1].startswith("text/html")
    assert get(base_url + "/static/app.js")[1].startswith("text/javascript")


@pytest.mark.parametrize("path", ["/nope", "/static/../server.py", "/static/missing.js"])
def test_unknown_paths_404(base_url, path):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base_url + path)
    assert e.value.code == 404


def test_binds_localhost_only(claude_dir, tmp_path):
    server = make_server(0, claude_dir.root, lambda: [], tmp_path / "c.json")
    assert server.server_address[0] == "127.0.0.1"
    server.server_close()
