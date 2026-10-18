"""Tiny stdlib HTTP server: the page, its assets, and /api/state."""
import json
import threading
import time
from collections.abc import Callable
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dashboard.discovery import LiveSession
from dashboard.snapshot import build_snapshot

STATIC = Path(__file__).parent / "static"
ASSETS = {"/": ("index.html", "text/html"),
          "/static/app.js": ("app.js", "text/javascript"),
          "/static/style.css": ("style.css", "text/css")}
SNAPSHOT_TTL_S = 2.0


class SnapshotCache:
    """Recompute at most every SNAPSHOT_TTL_S, however many tabs are polling."""

    def __init__(self, claude_dir: Path, sessions_fn: Callable[[], list[LiveSession]], ceiling_cache: Path):
        self.args = (claude_dir, sessions_fn)
        self.ceiling_cache = ceiling_cache
        self.lock = threading.Lock()
        self.at = 0.0
        self.body = b""

    def get(self) -> bytes:
        with self.lock:
            now = time.time()
            if now - self.at > SNAPSHOT_TTL_S:
                self.body = json.dumps(build_snapshot(*self.args, now, self.ceiling_cache)).encode()
                self.at = now
            return self.body


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, cache: SnapshotCache, **kwargs):
        self.cache = cache
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            self._send(200, "application/json", self.cache.get())
        elif path in ASSETS:  # whitelist: no filesystem paths from the URL
            name, ctype = ASSETS[path]
            self._send(200, f"{ctype}; charset=utf-8", (STATIC / name).read_bytes())
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # keep the terminal quiet; polling is noisy
        pass


def make_server(port: int, claude_dir: Path, sessions_fn: Callable[[], list[LiveSession]],
                ceiling_cache: Path) -> ThreadingHTTPServer:
    cache = SnapshotCache(claude_dir, sessions_fn, ceiling_cache)
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, cache=cache))
