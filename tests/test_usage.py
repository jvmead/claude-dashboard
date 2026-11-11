import json
from datetime import UTC, datetime

from dashboard.usage import block_start, ceiling_samples, collect, estimate, limits, peak, week_yellow, weighted
from tests.conftest import assistant

H = 3600
U = {"input_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0}


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat()


def rejection(t: float, resets_at: float) -> dict:
    return {"type": "assistant", "timestamp": iso(t), "isApiErrorMessage": True,
            "quotaLimits": {"status": "rejected", "rateLimitType": "five_hour", "resetsAt": resets_at},
            "message": {"id": "err", "model": "x", "content": [], "usage": {"input_tokens": 0}}}


def test_weights():
    u = {"input_tokens": 10, "cache_creation_input_tokens": 4, "cache_read_input_tokens": 100,
         "output_tokens": 2}
    assert weighted(u, "claude-opus-5-5") == 10 + 5 + 10 + 10
    assert weighted(u, "claude-haiku-5-5") == 0.2 * 35
    assert weighted(u, "claude-sonnet-5-5") == 0.6 * 35


def test_collect_dedupes_message_ids(claude_dir):
    t = 1_800_000_000
    claude_dir.add_session("s1", [assistant(iso(t), usage=U, msg_id="a"),
                                  assistant(iso(t), usage=U, msg_id="a"),
                                  assistant(iso(t + 60), usage=U, msg_id="b")])
    assert [w for _, w, _ in collect(claude_dir.root, since=0)] == [100, 100]


def test_block_start_rolls_over_after_5h():
    t0 = 1_800_000_000 - 1_800_000_000 % H + 600  # 10 min past an hour
    assert block_start([t0, t0 + H], now=t0 + 2 * H) == t0 - 600
    assert block_start([t0, t0 + 5 * H + 60], now=t0 + 5 * H + 120) == t0 + 5 * H - 600
    assert block_start([t0], now=t0 + 6 * H) is None


def test_ceiling_from_rejection(claude_dir, tmp_path):
    reset = 1_800_000_000
    claude_dir.add_session("s1", [assistant(iso(reset - 6 * H), usage=U, msg_id="old"),  # before window
                                  assistant(iso(reset - 4 * H), usage=U, msg_id="a"),
                                  assistant(iso(reset - 2 * H), usage=U, msg_id="b"),
                                  rejection(reset - 2 * H + 30, reset)])
    assert ceiling_samples(claude_dir.root, tmp_path / "ceilings.json") == [200]
    assert (tmp_path / "ceilings.json").exists()


def test_no_ceiling_samples(claude_dir, tmp_path):
    now = 1_800_000_000
    claude_dir.add_session("s1", [assistant(iso(now - 20 * 60), usage=U, msg_id="a")])
    e = estimate(claude_dir.root, now, tmp_path / "c.json")
    assert e["used"] == 100 and e["ceiling_median"] is None and e["minutes_left_lo"] is None
    assert e["burn_per_min"] == 100 / 30
    assert e["label"] == "this machine only"


def test_minutes_left_with_ceiling(claude_dir, tmp_path):
    reset = 1_700_000_000
    now = 1_800_000_000
    claude_dir.add_session("old", [assistant(iso(reset - H), usage={**U, "input_tokens": 3100}, msg_id="z"),
                                   rejection(reset - H + 10, reset)])
    claude_dir.add_session("s1", [assistant(iso(now - 10 * 60), usage=U, msg_id="a")])
    e = estimate(claude_dir.root, now, tmp_path / "c.json")
    assert e["ceiling_median"] == 3100
    assert e["minutes_left_lo"] == e["minutes_left_hi"] == (3100 - 100) / (100 / 30)
    assert not e["above_samples"]


def test_usage_above_every_sample_is_flagged(claude_dir, tmp_path):
    reset, now = 1_700_000_000, 1_800_000_000
    claude_dir.add_session("old", [assistant(iso(reset - H), usage={**U, "input_tokens": 50}, msg_id="z"),
                                   rejection(reset - H + 10, reset)])
    claude_dir.add_session("s1", [assistant(iso(now - 10 * 60), usage=U, msg_id="a")])
    e = estimate(claude_dir.root, now, tmp_path / "c.json")
    assert e["above_samples"] and e["minutes_left_lo"] is None and e["minutes_left_hi"] is None


def test_limits_from_status_line_snapshot(claude_dir):
    now = 1_800_000_000
    assert limits(claude_dir.root, now) is None  # no status line yet
    d = claude_dir.root / "dashboard"
    d.mkdir(parents=True)
    five = {"used_percentage": 23.0, "resets_at": now + H}
    week = {"used_percentage": 41.0, "resets_at": now - 1}  # past its reset: dropped
    (d / "usage.json").write_text(json.dumps({"ts": now - 60, "rate_limits": {"five_hour": five, "seven_day": week}}))
    assert limits(claude_dir.root, now) == {"ts": now - 60, "five_hour": five}
    (d / "usage.json").write_text("{bad")
    assert limits(claude_dir.root, now) is None


def test_week_yellow_follows_the_reset_weekday():
    def week(reset: datetime) -> list[float]:  # threshold at noon-ish of each day of the window
        r = reset.timestamp()
        return [week_yellow(r, r - 7 * 86400 + d * 86400 + H) for d in range(7)]

    assert week(datetime(2026, 11, 17, 5)) == [10, 30, 50, 70, 70, 70, 90]  # Tue reset: Tue..Mon
    assert week(datetime(2026, 11, 16, 9)) == [10, 30, 50, 70, 90, 90, 90]  # Mon reset: Mon..Sun
    assert week(datetime(2026, 11, 14, 9)) == [10, 10, 10, 30, 50, 70, 90]  # Sat reset: Sat..Fri


def test_limits_adds_todays_weekly_threshold(claude_dir):
    reset = datetime(2026, 11, 17, 5).timestamp()
    now = reset - 5 * 86400 + H  # Thursday of a Tuesday-reset week
    d = claude_dir.root / "dashboard"
    d.mkdir(parents=True)
    week = {"used_percentage": 41.0, "resets_at": reset}
    (d / "usage.json").write_text(json.dumps({"ts": now, "rate_limits": {"seven_day": week}}))
    assert limits(claude_dir.root, now)["seven_day"] == {**week, "yellow": 50}


def test_peak_follows_pacific_time_across_dst():
    def at(*args) -> dict:
        return peak(datetime(*args, tzinfo=UTC).timestamp())

    assert at(2026, 11, 11, 12, 30) == {"on": False, "change_s": 1800}  # Wed, PST: peak is 13-19 UTC
    assert at(2026, 11, 11, 18, 0) == {"on": True, "change_s": 3600}
    assert at(2026, 7, 15, 12, 0) == {"on": True, "change_s": 6 * 3600}  # Wed, PDT: peak is 12-18 UTC
    assert at(2026, 3, 9, 12, 0)["on"] and not at(2026, 3, 6, 12, 0)["on"]  # DST starts Sun 8 Mar
    assert at(2026, 11, 2, 12, 30)["on"] is False and at(2026, 10, 30, 12, 30)["on"]  # ends Sun 1 Nov
    assert at(2026, 11, 13, 20, 0) == {"on": False, "change_s": (2 * 24 + 17) * 3600}  # Fri eve to Mon 13 UTC
