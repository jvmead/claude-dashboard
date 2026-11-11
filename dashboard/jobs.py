"""Background jobs: recently written *.log files in a folder, with tqdm progress when the log has it.

Nothing here knows about the job. A log counts as a job while it was written in the last RECENT_S,
and its progress is the last tqdm bar in its tail, if there is one. Logs without tqdm still show,
with how long since they were last written.
"""
import re
from dataclasses import dataclass
from pathlib import Path

RECENT_S = 30 * 60
TAIL_BYTES = 8192
# tqdm's default line: "desc: 45%|████▌     | 450/1000 [02:10<02:40, 3.45it/s]"
# ponytail: bars with no total ("450it [02:10, ...]") or a custom bar_format don't match and show
# as "no tqdm progress"; extend the pattern if a real job needs them.
TQDM = re.compile(r"(\d{1,3})%\|[^|\r\n]*\|\s*([^\s\[]+/[^\s\[]+)\s*\[([^\]\r\n]*)\]")


@dataclass
class Job:
    name: str
    path: str
    quiet_s: float  # seconds since the log was last written
    pct: int | None  # last tqdm percentage, None if the tail has no tqdm bar
    detail: str  # "450/1000 · 02:10<02:40, 3.45it/s", or "" without tqdm


def last_progress(tail: str) -> tuple[int, str] | None:
    """The last tqdm bar in some log text. tqdm redraws with \\r, so the newest match wins."""
    matches = list(TQDM.finditer(tail))
    if not matches:
        return None
    m = matches[-1]
    return min(100, int(m.group(1))), f"{m.group(2)} · {m.group(3)}"


def _tail(path: Path) -> str:
    with path.open("rb") as f:
        size = f.seek(0, 2)
        f.seek(max(0, size - TAIL_BYTES))
        return f.read().decode("utf-8", errors="replace")


def load_jobs(log_dir: Path | None, now: float) -> list[Job]:
    """Recently written logs, newest first. No folder configured or present means no jobs."""
    if log_dir is None or not log_dir.is_dir():
        return []
    jobs = []
    for path in log_dir.glob("*.log"):
        try:
            mtime = path.stat().st_mtime
            if now - mtime > RECENT_S:
                continue
            progress = last_progress(_tail(path))
        except OSError:  # vanished or locked since the glob
            continue
        pct, detail = progress if progress else (None, "")
        jobs.append(Job(path.stem, str(path), max(0.0, now - mtime), pct, detail))
    return sorted(jobs, key=lambda j: j.quiet_s)
