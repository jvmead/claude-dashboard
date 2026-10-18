"""Live sessions via `claude agents --json` (native since Agent View)."""
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

TIMEOUT_S = 10


class DiscoveryError(RuntimeError):
    pass


@dataclass
class LiveSession:
    pid: int
    cwd: str
    session_id: str
    name: str
    busy: bool
    started: float


def list_sessions(runner: Callable = subprocess.run) -> list[LiveSession]:
    try:
        proc = runner(["claude", "agents", "--json"], capture_output=True, text=True, timeout=TIMEOUT_S)
    except FileNotFoundError as e:
        raise DiscoveryError("`claude` not found on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise DiscoveryError(f"`claude agents --json` timed out after {TIMEOUT_S}s") from e
    if proc.returncode != 0:
        raise DiscoveryError(f"`claude agents --json` failed: {proc.stderr.strip()[:200]}")
    try:
        rows = json.loads(proc.stdout)
        return [LiveSession(r["pid"], r["cwd"], r["sessionId"], r.get("name") or r["sessionId"][:8],
                            r.get("status") == "busy", r["startedAt"] / 1000) for r in rows]
    except (ValueError, KeyError, TypeError) as e:
        raise DiscoveryError(f"unexpected `claude agents --json` output: {e}") from e
