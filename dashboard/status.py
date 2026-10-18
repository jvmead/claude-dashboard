"""Session state model: what does this session need from me right now?"""
from enum import StrEnum

PARKED_AFTER_S = 1800


class State(StrEnum):
    APPROVAL = "approval"    # permission prompt pending
    YOUR_TURN = "your_turn"  # idle, nothing running, recently active
    WAITING = "waiting"      # idle but its own subagents are still running
    WORKING = "working"      # busy
    PARKED = "parked"        # idle and untouched for > PARKED_AFTER_S


SORT_ORDER = [State.APPROVAL, State.YOUR_TURN, State.WAITING, State.WORKING, State.PARKED]


def classify(busy: bool, outstanding: int, idle_seconds: float, approval_pending: bool) -> State:
    if approval_pending:
        return State.APPROVAL
    if busy:
        return State.WORKING
    if outstanding > 0:
        return State.WAITING
    return State.YOUR_TURN if idle_seconds <= PARKED_AFTER_S else State.PARKED

