from __future__ import annotations

import pytest

from shea.contracts.enums import TaskState
from shea.state_machine.transitions import (
    TERMINAL_STATES,
    IllegalTransitionError,
    allowed_events,
    is_terminal,
    next_state,
    validate_transition,
)


def test_happy_path_reaches_completed() -> None:
    state = TaskState.CREATED
    for event in [
        "start_planning",
        "plan_ready",
        "authorize_and_run",
        "execution_complete",
        "verified",
    ]:
        state = next_state(state, event)
    assert state == TaskState.COMPLETED


@pytest.mark.parametrize(
    "state,event",
    [
        (TaskState.CREATED, "authorize_and_run"),  # skip planning entirely
        (TaskState.CREATED, "execution_complete"),
        (TaskState.PLANNING, "authorize_and_run"),  # skip READY
        (TaskState.READY, "execution_complete"),  # skip RUNNING
        (TaskState.COMPLETED, "cancel"),  # terminal state, no way out
        (TaskState.CANCELLED, "start_planning"),
        (TaskState.SECURITY_HALT, "authorize_and_run"),
    ],
)
def test_illegal_transitions_are_rejected(state: TaskState, event: str) -> None:
    assert validate_transition(state, event) is False
    with pytest.raises(IllegalTransitionError):
        next_state(state, event)


def test_no_event_reaches_running_without_authorize_and_run() -> None:
    """The specific invariant this state machine exists to enforce:
    PLAN != AUTHORIZATION (Appendix B). There must be no path into RUNNING
    except through the single event that names authorization explicitly.
    """
    for state in TaskState:
        for event, target in allowed_events_map(state).items():
            if target == TaskState.RUNNING:
                assert event == "authorize_and_run"


def allowed_events_map(state: TaskState) -> dict[str, TaskState]:
    from shea.state_machine.transitions import TRANSITIONS

    return TRANSITIONS.get(state, {})


@pytest.mark.parametrize("state", list(TERMINAL_STATES))
def test_terminal_states_have_no_outgoing_transitions(state: TaskState) -> None:
    assert allowed_events(state) == frozenset()
    assert is_terminal(state) is True


@pytest.mark.parametrize(
    "state", [s for s in TaskState if s not in TERMINAL_STATES]
)
def test_non_terminal_states_have_at_least_one_transition(state: TaskState) -> None:
    assert len(allowed_events(state)) > 0
    assert is_terminal(state) is False


def test_illegal_transition_error_message_contains_state_and_event() -> None:
    with pytest.raises(IllegalTransitionError) as exc_info:
        next_state(TaskState.COMPLETED, "cancel")
    assert exc_info.value.current == TaskState.COMPLETED
    assert exc_info.value.event == "cancel"
