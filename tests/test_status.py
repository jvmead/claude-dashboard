from dashboard.status import State, approval_pending, classify


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


def test_approval_pending_needs_a_prompt():
    assert not approval_pending(None, 100.0)


def test_prompt_after_last_activity_is_pending():
    assert approval_pending(200.0, 100.0)
    assert not approval_pending(100.0, 200.0)
