"""python -m dashboard [--port 8765] [--claude-dir ~/.claude] [--open]"""

import argparse
import errno
import webbrowser
from pathlib import Path

from dashboard.discovery import list_sessions
from dashboard.server import make_server


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Local dashboard for live Claude Code sessions")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--claude-dir", type=Path, default=Path.home() / ".claude")
    p.add_argument(
        "--open",
        action="store_true",
        help="open a browser tab; if the port is already taken, assume the dashboard is running and just open it",
    )
    args = p.parse_args(argv)
    url = f"http://127.0.0.1:{args.port}"
    try:
        server = make_server(args.port, args.claude_dir, list_sessions, args.claude_dir / "dashboard" / "ceilings.json")
    except OSError as e:
        if args.open and e.errno == errno.EADDRINUSE:
            webbrowser.open(url)
            return
        raise
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Claude dashboard on {url}  (Ctrl+C to stop)")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
