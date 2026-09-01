from __future__ import annotations

from shea.contracts.enums import ExecutionOutcome, FailureCategory, RecoveryStrategy
from shea.contracts.models import (
    FailureClassification,
    RecoveryDecision,
    RetryPolicy,
    ToolExecutionRecord,
    VerificationRecord,
)


class RecoveryPlanner:
    """Selects the safest deterministic recovery strategy."""

    def __init__(self, retry_policy: RetryPolicy | None = None) -> None:
        self._retry_policy = retry_policy or RetryPolicy()

    def decide(
        self,
        record: ToolExecutionRecord,
        classification: FailureClassification,
        *,
        attempts_made: int,
        verification: VerificationRecord | None = None,
    ) -> RecoveryDecision:
        if classification.security_relevant:
            return RecoveryDecision(
                strategy=RecoveryStrategy.SECURITY_HALT,
                reason=classification.explanation,
                requires_verification=False,
                safe_to_retry=False,
            )

        if attempts_made >= self._retry_policy.max_attempts:
            return RecoveryDecision(
                strategy=RecoveryStrategy.ABORT,
                reason="Recovery attempt budget has been exhausted.",
                safe_to_retry=False,
            )

        if record.outcome is ExecutionOutcome.UNKNOWN:
            if verification is None:
                return RecoveryDecision(
                    strategy=RecoveryStrategy.REVERIFY,
                    reason=(
                        "Execution outcome is unknown; external state must be "
                        "verified before retrying."
                    ),
                    requires_verification=True,
                    safe_to_retry=False,
                )

            if verification.side_effect_detected:
                return RecoveryDecision(
                    strategy=RecoveryStrategy.ABORT,
                    reason=(
                        "The operation may already have produced its side effect; "
                        "retrying could duplicate it."
                    ),
                    requires_verification=False,
                    safe_to_retry=False,
                )

            if verification.retry_safe:
                return RecoveryDecision(
                    strategy=RecoveryStrategy.RETRY,
                    reason="Verification confirmed that retrying is safe.",
                    safe_to_retry=True,
                )

            return RecoveryDecision(
                strategy=RecoveryStrategy.ESCALATE,
                reason=(
                    "The operation's external state could not be established "
                    "as safe to retry."
                ),
                requires_verification=True,
                safe_to_retry=False,
            )

        if classification.retryable:
            if (
                self._retry_policy.require_idempotency
                and not record.idempotency_key
            ):
                return RecoveryDecision(
                    strategy=RecoveryStrategy.REVERIFY,
                    reason=(
                        "Retry requires an idempotency key or independent "
                        "verification."
                    ),
                    requires_verification=True,
                    safe_to_retry=False,
                )

            return RecoveryDecision(
                strategy=RecoveryStrategy.RETRY,
                reason=classification.explanation,
                safe_to_retry=True,
            )

        if classification.reversible:
            return RecoveryDecision(
                strategy=RecoveryStrategy.COMPENSATE,
                reason=classification.explanation,
                requires_verification=True,
            )

        if classification.category is FailureCategory.PERMANENT:
            return RecoveryDecision(
                strategy=RecoveryStrategy.ABORT,
                reason=classification.explanation,
            )

        return RecoveryDecision(
            strategy=RecoveryStrategy.ESCALATE,
            reason=classification.explanation,
            requires_verification=classification.requires_verification,
        )