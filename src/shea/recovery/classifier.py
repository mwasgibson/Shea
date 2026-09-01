from __future__ import annotations

from shea.contracts.enums import ExecutionOutcome, FailureCategory
from shea.contracts.models import FailureClassification, ToolExecutionRecord


class FailureClassifier:
    """Converts execution failures into deterministic recovery categories."""

    def classify(
        self,
        record: ToolExecutionRecord,
    ) -> FailureClassification:
        if record.outcome is ExecutionOutcome.UNKNOWN:
            return FailureClassification(
                category=FailureCategory.UNKNOWN_OUTCOME,
                retryable=False,
                recoverable=True,
                reversible=True,
                requires_verification=True,
                security_relevant=False,
                explanation=(
                    "The execution outcome is unknown. The external side effect "
                    "must be verified before another attempt."
                ),
            )

        error = (record.error or "").lower()

        if any(value in error for value in ("timeout", "timed out")):
            return FailureClassification(
                category=FailureCategory.TIMEOUT,
                retryable=True,
                recoverable=True,
                reversible=False,
                requires_verification=True,
                security_relevant=False,
                explanation="The operation timed out.",
            )

        if any(
            value in error
            for value in ("connection", "network", "dns", "connection reset")
        ):
            return FailureClassification(
                category=FailureCategory.NETWORK,
                retryable=True,
                recoverable=True,
                reversible=False,
                requires_verification=True,
                security_relevant=False,
                explanation="The operation failed because of a network condition.",
            )

        if any(
            value in error
            for value in ("rate limit", "too many requests", "429")
        ):
            return FailureClassification(
                category=FailureCategory.RATE_LIMITED,
                retryable=True,
                recoverable=True,
                reversible=False,
                requires_verification=True,
                security_relevant=False,
                explanation="The operation was rate limited.",
            )

        if any(
            value in error
            for value in ("permission denied", "forbidden", "not authorized")
        ):
            return FailureClassification(
                category=FailureCategory.AUTHORIZATION,
                retryable=False,
                recoverable=False,
                reversible=False,
                requires_verification=False,
                security_relevant=True,
                explanation="The operation was not authorized.",
            )

        if any(
            value in error
            for value in ("unauthenticated", "authentication", "invalid token")
        ):
            return FailureClassification(
                category=FailureCategory.AUTHENTICATION,
                retryable=False,
                recoverable=True,
                reversible=False,
                requires_verification=False,
                security_relevant=True,
                explanation="Authentication failed.",
            )

        if any(
            value in error
            for value in ("invalid argument", "invalid input", "validation error")
        ):
            return FailureClassification(
                category=FailureCategory.INVALID_INPUT,
                retryable=False,
                recoverable=False,
                reversible=False,
                requires_verification=False,
                security_relevant=False,
                explanation="The operation received invalid input.",
            )

        if any(
            value in error
            for value in ("security", "malicious", "integrity violation")
        ):
            return FailureClassification(
                category=FailureCategory.SECURITY,
                retryable=False,
                recoverable=False,
                reversible=False,
                requires_verification=False,
                security_relevant=True,
                explanation="The failure is security relevant.",
            )

        return FailureClassification(
            category=FailureCategory.UNKNOWN,
            retryable=False,
            recoverable=True,
            reversible=False,
            requires_verification=True,
            security_relevant=False,
            explanation="The failure could not be safely classified.",
        )