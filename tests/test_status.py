from dashboard.status import State, classify


def test_approval_beats_everything():
    assert classify(busy=True, outstanding=3, idle_seconds=9999, approval_pending=True) is State.APPROVAL


def test_busy_is_working():
    assert classify(busy=True, outstanding=2, idle_seconds=0, approval_pending=False) is State.WORKING


def test_idle_with_outstanding_subagents_is_waiting():
    assert classify(busy=False, outstanding=1, idle_seconds=5000, approval_pending=False) is State.WAITING


def test_idle_recently_is_your_turn():
    assert classify(busy=False, outstanding=0, idle_seconds=1800, approval_pending=False) is State.YOUR_TURN


def test_idle_over_30_min_is_parked():
    assert classify(busy=False, outstanding=0, idle_seconds=1801, approval_pending=False) is State.PARKED
