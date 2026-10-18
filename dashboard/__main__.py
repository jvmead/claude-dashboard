"""python -m dashboard [--port 8765] [--claude-dir ~/.claude]"""
import argparse
from pathlib import Path

from dashboard.discovery import list_sessions
from dashboard.server import make_server


def main() -> None:
    p = argparse.ArgumentParser(description="Local dashboard for live Claude Code sessions")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--claude-dir", type=Path, default=Path.home() / ".claude")
    args = p.parse_args()
    server = make_server(args.port, args.claude_dir, list_sessions,
                         args.claude_dir / "dashboard" / "ceilings.json")
    print(f"Claude dashboard on http://127.0.0.1:{server.server_address[1]}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
