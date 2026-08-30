from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from shea.contracts.enums import ExecutionOutcome, TaskState
from shea.contracts.models import Task, ToolExecutionRecord
from shea.recovery.compensator import default_compensator
from shea.verification.verifier import default_verifier


def make_task() -> Task:
    return Task(
        id="task-1",
        session_id="session-1",
        request_id="req-1",
        state=TaskState.VERIFYING,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@given(
    success=st.booleans(),
    outcome=st.sampled_from(list(ExecutionOutcome)),
    tool=st.text(min_size=1, max_size=10),
)
def test_default_verifier_only_verifies_genuine_success(
    success: bool, outcome: ExecutionOutcome, tool: str
) -> None:
    """The default verifier must never report verified=True unless the
    execution record itself reported both SUCCESS and success=True —
    across every combination of outcome and success flag.
    """
    record = ToolExecutionRecord(
        id="exec-1",
        task_id="task-1",
        tool=tool,
        action="do_thing",
        outcome=outcome,
        success=success,
    )
    result = default_verifier(make_task(), record)

    expected = outcome is ExecutionOutcome.SUCCESS and success is True
    assert result.verified == expected


@given(task_id=st.text(min_size=1, max_size=10))
def test_default_compensator_never_reports_restored(task_id: str) -> None:
    """Constraint 5, as a property: with no real compensating action
    configured, the default must always report `restored=False`,
    regardless of what task it's given.
    """
    task = Task(
        id=task_id,
        session_id="session-1",
        request_id="req-1",
        state=TaskState.RECOVERING,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    outcome = default_compensator(task)
    assert outcome.restored is False