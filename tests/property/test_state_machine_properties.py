from __future__ import annotations

import string

from hypothesis import given
from hypothesis import strategies as st

from shea.contracts.enums import TaskState
from shea.state_machine.transitions import (
    TERMINAL_STATES,
    TRANSITIONS,
    IllegalTransitionError,
    next_state,
    validate_transition,
)

task_states = st.sampled_from(list(TaskState))

# Random event-like strings, intentionally including some real event names
# so the strategy isn't trivially always-illegal.
event_strings = st.one_of(
    st.sampled_from(
        sorted({event for events in TRANSITIONS.values() for event in events})
    ),
    st.text(alphabet=string.ascii_lowercase + "_", min_size=1, max_size=20),
)


@given(state=task_states, event=event_strings)
def test_next_state_agrees_with_validate_transition(state: TaskState, event: str) -> None:
    """Core architectural property (technical doc Section 19): an event
    either is legal, in which case next_state succeeds and matches the
    table, or it is not, in which case next_state always raises — there is
    no third outcome, and the two functions can never disagree.
    """
    if validate_transition(state, event):
        result = next_state(state, event)
        assert result == TRANSITIONS[state][event]
    else:
        try:
            next_state(state, event)
        except IllegalTransitionError as exc:
            assert exc.current == state
            assert exc.event == event
        else:
            raise AssertionError("expected IllegalTransitionError")


@given(state=st.sampled_from(list(TERMINAL_STATES)), event=event_strings)
def test_terminal_states_reject_every_event(state: TaskState, event: str) -> None:
    """An unauthorized/illegal request must never reach a "completed" task
    and move it somewhere else — technical doc Section 19's property-based
    testing example, applied to terminal states specifically.
    """
    assert validate_transition(state, event) is False
    try:
        next_state(state, event)
    except IllegalTransitionError:
        pass
    else:
        raise AssertionError("terminal state must reject every event")


@given(state=task_states, event=event_strings)
def test_running_is_only_reachable_via_authorize_and_run(
    state: TaskState, event: str
) -> None:
    """PLAN != AUTHORIZATION (Appendix B), stated as a property: no event
    other than `authorize_and_run` may ever transition a task into RUNNING.
    """
    if validate_transition(state, event):
        result = next_state(state, event)
        if result == TaskState.RUNNING:
            assert event == "authorize_and_run"
