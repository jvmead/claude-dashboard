import os

from dashboard.jobs import RECENT_S, last_progress, load_jobs

NOW = 1_800_000_000


def write(path, text, age_s):
    path.write_text(text, encoding="utf-8")
    os.utime(path, (NOW - age_s, NOW - age_s))


def test_last_tqdm_redraw_wins():
    tail = ("loading\n 10%|█         | 100/1000 [00:10<01:30, 10.0it/s]"
            "\r 45%|████▌     | 450/1000 [00:45<00:55, 10.0it/s]")
    assert last_progress(tail) == (45, "450/1000 · 00:45<00:55, 10.0it/s")


def test_ascii_bar_and_description():
    assert last_progress("fit: 100%|##########| 12/12 [00:03<00:00]\n") == (100, "12/12 · 00:03<00:00")


def test_no_tqdm():
    assert last_progress("2026-10-22 INFO step 3 of 10 done\n") is None


def test_load_jobs(tmp_path):
    write(tmp_path / "train.log", " 30%|###       | 3/10 [00:01<00:02]", age_s=5)
    write(tmp_path / "plain.log", "INFO started\n", age_s=120)
    write(tmp_path / "old.log", " 50%|#####     | 5/10 [00:01<00:01]", age_s=RECENT_S + 1)
    write(tmp_path / "notes.txt", " 50%|#####     | 5/10 [00:01<00:01]", age_s=5)
    jobs = load_jobs(tmp_path, NOW)
    assert [(j.name, j.pct, j.quiet_s) for j in jobs] == [("train", 30, 5), ("plain", None, 120)]


def test_missing_or_unset_folder(tmp_path):
    assert load_jobs(None, NOW) == [] and load_jobs(tmp_path / "nope", NOW) == []
