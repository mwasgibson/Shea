from __future__ import annotations

from shea.contracts.enums import TaskState

# States with no outgoing transitions. A task that reaches one of these
# is done, one way or another, and stays there.
TERMINAL_STATES: frozenset[TaskState] = frozenset(
    {TaskState.COMPLETED, TaskState.CANCELLED, TaskState.SECURITY_HALT}
)

# The single source of truth for legal task transitions. Every event name
# here is a *reason* the orchestrator advances a task — never a raw target
# state string — so a caller can't accidentally jump a task from CREATED
# straight to RUNNING by passing the "right" string. This is what makes
# Appendix B's `PLAN != AUTHORIZATION` structural rather than a convention:
# there is no event in this table that goes directly from READY to RUNNING
# without passing through an authorization step first.
TRANSITIONS: dict[TaskState, dict[str, TaskState]] = {
    TaskState.CREATED: {
        "start_planning": TaskState.PLANNING,
        "cancel": TaskState.CANCELLED,
    },
    TaskState.PLANNING: {
        "plan_ready": TaskState.READY,
        "plan_failed": TaskState.FAILED,
        "block": TaskState.BLOCKED,
        "cancel": TaskState.CANCELLED,
    },
    TaskState.READY: {
        # The event name makes explicit that entering RUNNING requires an
        # authorization to have already happened upstream — the state
        # machine doesn't verify *that* authorization occurred (the
        # Decision/Authorization subsystem does, in a later phase), but it
        # refuses to let any other path reach RUNNING.
        "authorize_and_run": TaskState.RUNNING,
        "block": TaskState.BLOCKED,
        "cancel": TaskState.CANCELLED,
    },
    TaskState.RUNNING: {
        "execution_complete": TaskState.VERIFYING,
        "execution_failed": TaskState.FAILED,
        "security_halt": TaskState.SECURITY_HALT,
        "cancel": TaskState.CANCELLED,
    },
    TaskState.VERIFYING: {
        "verified": TaskState.COMPLETED,
        "verification_failed": TaskState.FAILED,
    },
    TaskState.FAILED: {
        "retry": TaskState.RECOVERING,
    },
    TaskState.RECOVERING: {
        "recovered": TaskState.READY,
        "recovery_failed": TaskState.FAILED,
    },
    TaskState.BLOCKED: {
        "unblock": TaskState.READY,
        "cancel": TaskState.CANCELLED,
    },
    # Terminal states intentionally have no entry in TRANSITIONS at all,
    # so `.get(state, {})` naturally yields no allowed events for them.
}


class IllegalTransitionError(Exception):
    """Raised whenever an event is not legal from the task's current state.

    This includes events that would target a terminal state's "successor" —
    terminal states simply have no entries, so any event raises this.
    """

    def __init__(self, current: TaskState, event: str) -> None:
        self.current = current
        self.event = event
        super().__init__(
            f"Illegal transition: event {event!r} is not valid from state {current.value!r}"
        )


def is_terminal(state: TaskState) -> bool:
    return state in TERMINAL_STATES


def allowed_events(state: TaskState) -> frozenset[str]:
    return frozenset(TRANSITIONS.get(state, {}).keys())


def validate_transition(current: TaskState, event: str) -> bool:
    return event in TRANSITIONS.get(current, {})


def next_state(current: TaskState, event: str) -> TaskState:
    """Compute the next state, or raise IllegalTransitionError.

    This is the only function that should ever change a Task's `state`
    field. The orchestrator calls this rather than assigning states by
    hand, so "an unauthorized/illegal transition must never reach
    persistence" (technical doc Section 19, property-based testing) holds
    by construction.
    """
    allowed = TRANSITIONS.get(current, {})
    if event not in allowed:
        raise IllegalTransitionError(current, event)
    return allowed[event]
