from __future__ import annotations

from shea.contracts.enums import (
    ExecutionOutcome,
    FailureCategory,
    RecoveryStrategy,
)
from shea.contracts.models import (
    FailureClassification,
    RetryPolicy,
    ToolExecutionRecord,
    VerificationRecord,
)
from shea.recovery.planner import RecoveryPlanner


def make_record(
    *,
    outcome: ExecutionOutcome = ExecutionOutcome.FAILURE,
    idempotency_key: str | None = "idem-1",
) -> ToolExecutionRecord:
    return ToolExecutionRecord(
        id="execution-1",
        task_id="task-1",
        tool="test_tool",
        action="test_action",
        outcome=outcome,
        success=False,
        error="failure",
        idempotency_key=idempotency_key,
    )

def make_classification(
    *,
    category: FailureCategory = FailureCategory.TRANSIENT,
    retryable: bool = True,
    recoverable: bool = True,
    reversible: bool = False,
    requires_verification: bool = False,
    security_relevant: bool = False,
) -> FailureClassification:
    return FailureClassification(
        category=category,
        retryable=retryable,
        recoverable=recoverable,
        reversible=reversible,
        requires_verification=requires_verification,
        security_relevant=security_relevant,
        explanation="test failure",
    )

def test_transient_failure_with_idempotency_retries() -> None:
    planner = RecoveryPlanner(
        RetryPolicy(
            max_attempts=3,
            require_idempotency=True,
        )
    )
    decision = planner.decide(
        make_record(),
        make_classification(),
        attempts_made=0,
    )
    assert decision.strategy is RecoveryStrategy.RETRY
    assert decision.safe_to_retry is True

def test_retry_requires_idempotency() -> None:
    planner = RecoveryPlanner(
        RetryPolicy(
            max_attempts=3,
            require_idempotency=True,
        )
    )
    decision = planner.decide(
        make_record(idempotency_key=None),
        make_classification(),
        attempts_made=0,
    )
    assert decision.strategy is RecoveryStrategy.REVERIFY
    assert decision.safe_to_retry is False
    assert decision.requires_verification is True

def test_security_failure_halts() -> None:
    planner = RecoveryPlanner()

    decision = planner.decide(
        make_record(),
        make_classification(
            category=FailureCategory.SECURITY,
            retryable=False,
            recoverable=False,
            security_relevant=True,
        ),
        attempts_made=0,
    )
    assert decision.strategy is RecoveryStrategy.SECURITY_HALT
    assert decision.safe_to_retry is False

def test_attempt_budget_exhaustion_aborts() -> None:
    planner = RecoveryPlanner(
        RetryPolicy(max_attempts=3)
    )

    decision = planner.decide(
        make_record(),
        make_classification(),
        attempts_made=3,
    )
    assert decision.strategy is RecoveryStrategy.ABORT
    assert decision.safe_to_retry is False

def test_unknown_outcome_requires_reverification() -> None:
    planner = RecoveryPlanner()

    decision = planner.decide(
        make_record(
            outcome=ExecutionOutcome.UNKNOWN,
    ),
    make_classification(
        category=FailureCategory.UNKNOWN_OUTCOME,
        retryable=False,
        requires_verification=True,
    ),
    attempts_made=0,
)

    assert decision.strategy is RecoveryStrategy.REVERIFY
    assert decision.requires_verification is True
    assert decision.safe_to_retry is False

def test_unknown_side_effect_prevents_retry() -> None:
    planner = RecoveryPlanner()

    verification = VerificationRecord(
        id="verification-1",
        task_id="task-1",
        verified=True,
        method="provider_lookup",
        explanation="Operation already occurred.",
        side_effect_detected=True,
        retry_safe=False,
    )

    decision = planner.decide(
        make_record(
            outcome=ExecutionOutcome.UNKNOWN,
        ),
        make_classification(
            category=FailureCategory.UNKNOWN_OUTCOME,
            retryable=False,
            requires_verification=True,
        ),
        attempts_made=0,
        verification=verification,
    )
    assert decision.strategy is RecoveryStrategy.ABORT
    assert decision.safe_to_retry is False

def test_verified_safe_unknown_outcome_can_retry() -> None:
    planner = RecoveryPlanner()

    verification = VerificationRecord(
        id="verification-1",
        task_id="task-1",
        verified=True,
        method="state_lookup",
        explanation="No side effect occurred.",
        side_effect_detected=False,
        retry_safe=True,
    )

    decision = planner.decide(
        make_record(
            outcome=ExecutionOutcome.UNKNOWN,
        ),
        make_classification(
            category=FailureCategory.UNKNOWN_OUTCOME,
            retryable=False,
            requires_verification=True,
        ),
        attempts_made=0,
        verification=verification,
    )
    assert decision.strategy is RecoveryStrategy.RETRY
    assert decision.safe_to_retry is True

def test_unresolved_unknown_outcome_escalates() -> None:
    planner = RecoveryPlanner()

    verification = VerificationRecord(
        id="verification-1",
        task_id="task-1",
        verified=False,
        method="state_lookup",
        explanation="External state could not be established.",
        side_effect_detected=False,
        retry_safe=False,
    )
    decision = planner.decide(
        make_record(
            outcome=ExecutionOutcome.UNKNOWN,
        ),
        make_classification(
            category=FailureCategory.UNKNOWN_OUTCOME,
            retryable=False,
            requires_verification=True,
        ),
        attempts_made=0,
        verification=verification,
    )
    assert decision.strategy is RecoveryStrategy.ESCALATE
    assert decision.safe_to_retry is False

def test_reversible_failure_compensates() -> None:
    planner = RecoveryPlanner()

    decision = planner.decide(
        make_record(),
        make_classification(
            retryable=False,
            recoverable=True,
            reversible=True,
            requires_verification=True,
        ),
        attempts_made=0,
    )
    assert decision.strategy is RecoveryStrategy.COMPENSATE
    assert decision.requires_verification is True