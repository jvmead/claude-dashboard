"""python -m dashboard [--port 8765] [--claude-dir ~/.claude] [--logs DIR] [--open | --json]"""

import argparse
import errno
import json
import time
import webbrowser
from pathlib import Path

from dashboard.discovery import list_sessions
from dashboard.server import make_server
from dashboard.snapshot import build_snapshot


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Local dashboard for live Claude Code sessions")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--claude-dir", type=Path, default=Path.home() / ".claude")
    p.add_argument(
        "--open",
        action="store_true",
        help="open a browser tab; if the port is already taken, assume the dashboard is running and just open it",
    )
    p.add_argument("--logs", type=Path, help="folder of background-job *.log files to list, with tqdm progress if present")
    p.add_argument("--json", action="store_true", help="print the sessions as JSON (no usage) and exit")
    args = p.parse_args(argv)
    ceilings = args.claude_dir / "dashboard" / "ceilings.json"
    if args.json:
        print(json.dumps(build_snapshot(args.claude_dir, list_sessions, time.time(), ceilings, args.logs, with_usage=False)))
        return
    url = f"http://127.0.0.1:{args.port}"
    try:
        server = make_server(args.port, args.claude_dir, list_sessions, ceilings, args.logs)
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
