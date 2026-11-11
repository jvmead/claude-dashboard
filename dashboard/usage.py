"""5-hour window estimate from local transcripts.

The real ceiling isn't stored anywhere; we infer it from past five_hour rejections
(usage in that window up to the rejection). Usage outside this machine is invisible.
"""
import json
import statistics
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from dashboard.transcripts import iter_records, parse_ts

WINDOW_S = 5 * 3600
BURN_WINDOW_S = 30 * 60
# Relative cost of token kinds, input = 1. ponytail: rough list-price ratios; a real fit
# against rejection samples would need more than the handful on record.
TOKEN_WEIGHTS = {"input_tokens": 1.0, "cache_creation_input_tokens": 1.25,
                 "cache_read_input_tokens": 0.1, "output_tokens": 5.0}
MODEL_FACTORS = {"opus": 1.0, "sonnet": 0.6, "haiku": 0.2}
DAY_S = 86400
WORKDAYS = frozenset(range(5))  # Mon..Fri as datetime.weekday(); the weekly budget is spread over these

Record = tuple[float, float, str]  # (timestamp, weight, message id)


def weighted(usage: dict, model: str) -> float:
    factor = next((f for name, f in MODEL_FACTORS.items() if name in (model or "")), 1.0)
    return factor * sum(w * (usage.get(k) or 0) for k, w in TOKEN_WEIGHTS.items())


@lru_cache(maxsize=4096)
def file_records(path: Path, _mtime_ns: int, _size: int) -> tuple[tuple[Record, ...], tuple[tuple[float, float], ...]]:
    """(usage records, five_hour rejections as (ts, resetsAt)) for one transcript."""
    records, rejections = [], []
    for rec in iter_records(path):
        if rec.get("type") != "assistant" or not rec.get("timestamp"):
            continue
        try:
            ts = parse_ts(rec["timestamp"])
            q = rec.get("quotaLimits")
            if isinstance(q, dict) and q.get("status") == "rejected" and q.get("rateLimitType") == "five_hour":
                rejections.append((ts, float(q["resetsAt"])))
            msg = rec.get("message") or {}
            if msg.get("usage") and not rec.get("isApiErrorMessage"):
                records.append((ts, weighted(msg["usage"], msg.get("model", "")), msg.get("id", "")))
        except (ValueError, TypeError, KeyError):  # malformed record: skip just it
            continue
    return tuple(records), tuple(rejections)


def _scan(claude_dir: Path, since: float = 0.0):
    for path in (claude_dir / "projects").glob("**/*.jsonl"):
        try:
            st = path.stat()
            if st.st_mtime >= since:
                yield file_records(path, st.st_mtime_ns, st.st_size)
        except OSError:  # vanished or unreadable since the glob
            continue


def collect(claude_dir: Path, since: float, until: float = float("inf")) -> list[Record]:
    """Usage records in [since, until], deduped on message id (streamed messages repeat)."""
    seen: dict[str, Record] = {}
    for records, _ in _scan(claude_dir, since):
        for r in records:
            if since <= r[0] <= until:
                seen.setdefault(r[2] or f"{r[0]}", r)
    return sorted(seen.values())


def block_start(timestamps: list[float], now: float) -> float | None:
    """ccusage rule: a block starts at its first activity floored to the hour and lasts 5 h."""
    start = None
    for t in sorted(timestamps):
        if start is None or t >= start + WINDOW_S:
            start = t - t % 3600
    return start if start is not None and now < start + WINDOW_S else None


def ceiling_samples(claude_dir: Path, cache_path: Path) -> list[float]:
    """Weighted usage at each past five_hour rejection, cached per window (keyed by resetsAt)."""
    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        cache = {}
    first_hit: dict[float, float] = {}
    for _, rejections in _scan(claude_dir):
        for ts, resets_at in rejections:
            first_hit[resets_at] = min(ts, first_hit.get(resets_at, ts))
    for resets_at, ts in first_hit.items():
        key = str(int(resets_at))
        if key not in cache:
            cache[key] = sum(w for _, w, _ in collect(claude_dir, resets_at - WINDOW_S, ts))
    if cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache))
    return [cache[str(int(r))] for r in sorted(first_hit) if cache[str(int(r))] > 0]


def _minutes_to(ceiling: float | None, used: float, burn: float) -> float | None:
    if ceiling is None or burn <= 0 or used > ceiling:
        return None
    return (ceiling - used) / burn


def week_yellow(resets_at: float, now: float) -> float:
    """Weekly usage (%) at which today turns yellow: halfway through today's share of an even
    spend over the window's working days. Days off hold the last working day's threshold."""
    # ponytail: a day is a 24 h block counted from the reset and takes the local weekday of its
    # start, so a mid-afternoon reset puts Friday evening and Saturday morning in one "Friday".
    # Upgrade path: integrate working hours instead of counting blocks.
    start = resets_at - 7 * DAY_S
    today = min(6, max(0, int((now - start) // DAY_S)))

    # working days in the window up to and including today
    done = sum(datetime.fromtimestamp(start + d * DAY_S).weekday() in WORKDAYS for d in range(today + 1))

    return (max(done, 1) - 0.5) * 100 / len(WORKDAYS)  # max: days off before the first working day use its threshold


PEAK_HOURS_PT = (5, 11)  # weekday hours, Pacific time, when 5-hour limits drain faster


def pacific_offset_h(t: datetime) -> int:
    """UTC offset of US Pacific time at instant t: -7 in daylight time, -8 otherwise."""
    # ponytail: hard-codes the US rule in force since 2007 (second Sunday of March to first
    # Sunday of November, 02:00 local) because Windows Python has no tz database without the
    # tzdata package. Upgrade path: zoneinfo("America/Los_Angeles") if tzdata becomes a dependency.
    def sunday(month: int, nth: int, hour_utc: int) -> datetime:
        first = datetime(t.year, month, 1, hour_utc, tzinfo=UTC)
        return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (nth - 1))

    return -7 if sunday(3, 2, 10) <= t < sunday(11, 1, 9) else -8


def peak(now: float) -> dict:
    """Whether now is in Anthropic's weekday peak window, and seconds until that changes."""
    def local(ts: float) -> datetime:
        t = datetime.fromtimestamp(ts, UTC)
        return t + timedelta(hours=pacific_offset_h(t))

    def is_peak(ts: float) -> bool:
        t = local(ts)
        return t.weekday() in WORKDAYS and PEAK_HOURS_PT[0] <= t.hour < PEAK_HOURS_PT[1]

    # step forward to the next whole Pacific hour where the state flips (at most a weekend away)
    on = is_peak(now)
    t = now - now % 3600 + 3600  # offsets are whole hours, so UTC and Pacific hours align
    while is_peak(t) == on and t < now + 4 * DAY_S:
        t += 3600
    return {"on": on, "change_s": t - now}


def limits(claude_dir: Path, now: float) -> dict | None:
    """Real plan usage from ~/.claude/dashboard/usage.json, written by the status line script
    from the rate_limits Claude Code passes it. Windows past their reset are dropped; None
    when the file is missing, unreadable or holds nothing current. The weekly window gains
    "yellow", today's pace threshold."""
    try:
        snap = json.loads((claude_dir / "dashboard" / "usage.json").read_text(encoding="utf-8"))
        windows = {k: w for k, w in (snap.get("rate_limits") or {}).items()
                   if k in ("five_hour", "seven_day") and w and w.get("resets_at", 0) > now}
        if "seven_day" in windows:
            windows["seven_day"]["yellow"] = week_yellow(windows["seven_day"]["resets_at"], now)
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    return {"ts": snap.get("ts"), **windows} if windows else None


def estimate(claude_dir: Path, now: float, cache_path: Path) -> dict:
    records = collect(claude_dir, now - 2 * WINDOW_S, now)
    start = block_start([t for t, _, _ in records], now)
    used = sum(w for t, w, _ in records if start is not None and t >= start)
    burn = sum(w for t, w, _ in records if t >= now - BURN_WINDOW_S) / (BURN_WINDOW_S / 60)
    samples = ceiling_samples(claude_dir, cache_path)
    median = statistics.median(samples) if samples else None
    return {
        "used": used,
        "block_start": start,
        "block_end": start + WINDOW_S if start is not None else None,
        "burn_per_min": burn,
        "ceiling_median": median,
        "ceiling_lo": min(samples, default=None),
        "ceiling_hi": max(samples, default=None),
        "samples": len(samples),
        # A range, not a point: samples disagree (limits and model mix change over time).
        "minutes_left_lo": _minutes_to(min(samples, default=None), used, burn),
        "minutes_left_hi": _minutes_to(max(samples, default=None), used, burn),
        "above_samples": bool(samples) and used > max(samples),
        "label": "this machine only",
        "limits": limits(claude_dir, now),
    }
