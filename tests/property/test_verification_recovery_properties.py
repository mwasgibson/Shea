from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from shea.contracts.enums import ExecutionOutcome, TaskState
from shea.contracts.models import Task, ToolExecutionRecord
from shea.recovery.classifier import FailureClassifier
from shea.recovery.compensator import default_compensator
from shea.recovery.planner import RecoveryPlanner
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

def make_execution(
    *,
    success: bool,
    outcome: ExecutionOutcome,
    error: str | None = None,
    idempotency_key: str | None = "idem-1",
) -> ToolExecutionRecord:
    return ToolExecutionRecord(
        id="exec-1",
        task_id="task-1",
        tool="test_tool",
        action="do_thing",
        outcome=outcome,
        success=success,
        error=error,
        idempotency_key=idempotency_key,
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
    
        
@given(
    error=st.sampled_from(
        [ 
         "timeout", "request timed out", "connection reset by peer", 
         "network unavailable", "HTTP 429 too many requests",
        ]
    )
)
def test_retryable_failures_are_classified_as_retryable(
    error: str,
) -> None:
    """Transient infrastructure failures must remain retryable."""
    record = make_execution(
    success=False,
    outcome=ExecutionOutcome.FAILURE,
    error=error,
    )
    result = FailureClassifier().classify(record)
    assert result.retryable is True
    assert result.security_relevant is False

@given(
    error=st.sampled_from(
        [ "permission denied", "forbidden", "not authorized",]
    )
)
def test_authorization_failures_are_never_blindly_retryable(
    error: str,
) -> None:
    """Authorization failures must not be treated as ordinary retries."""
    record = make_execution(
        success=False,
        outcome=ExecutionOutcome.FAILURE,
        error=error,
    )
    result = FailureClassifier().classify(record)
    assert result.retryable is False
    assert result.security_relevant is True

@given(
error=st.text(min_size=1, max_size=200)
)
def test_unknown_failure_is_not_automatically_retryable(
    error: str,
) -> None:
    """An unrecognized failure must fail closed rather than becoming a
    blind retry.
    """
    record = make_execution(
        success=False,
        outcome=ExecutionOutcome.FAILURE,
        error=error,
    )
    result = FailureClassifier().classify(record)
    if result.category.value == "UNKNOWN":
        assert result.retryable is False

def test_unknown_execution_outcome_requires_verification() -> None:
    """An UNKNOWN outcome means Shea cannot know whether the external
    side effect happened. Verification must therefore happen first.
    """
    record = make_execution(
        success=False,
        outcome=ExecutionOutcome.UNKNOWN,
        error=None,
    )
    result = FailureClassifier().classify(record)
    assert result.retryable is False
    assert result.requires_verification is True

@given(
attempts=st.integers(min_value=0, max_value=100)
)
def test_recovery_planner_never_retries_after_attempt_budget(
    attempts: int,
) -> None:
    """Once the configured recovery budget is exhausted, the planner
    must never select RETRY.
    """
    planner = RecoveryPlanner()
    record = make_execution(
        success=False,
        outcome=ExecutionOutcome.FAILURE,
        error="timeout",
    )
    classification = FailureClassifier().classify(record)
    if attempts >= 3:
        decision = planner.decide(
            record,
            classification,
            attempts_made=attempts,
        )
        assert decision.safe_to_retry is False
        assert decision.strategy.value != "RETRY"

def test_security_failure_never_produces_retry_decision() -> None:
    """Security-relevant failures must stop recovery rather than retry."""
    record = make_execution(
        success=False,
        outcome=ExecutionOutcome.FAILURE,
        error="security integrity violation",
    )
    classification = FailureClassifier().classify(record)
    decision = RecoveryPlanner().decide(
        record,
        classification,
        attempts_made=0,
    )
    assert decision.strategy.value != "RETRY"
    assert decision.safe_to_retry is False

def test_retry_without_idempotency_requires_verification() -> None:
    """A retryable operation without an idempotency key must not be
    blindly executed again.
    """
    record = make_execution(
        success=False,
        outcome=ExecutionOutcome.FAILURE,
        error="timeout",
        idempotency_key=None,
    )
    classification = FailureClassifier().classify(record)
    decision = RecoveryPlanner().decide(
        record,
        classification,
        attempts_made=0,
    )
    assert decision.strategy.value == "REVERIFY"
    assert decision.requires_verification is True
    assert decision.safe_to_retry is False    