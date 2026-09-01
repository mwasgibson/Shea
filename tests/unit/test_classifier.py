from __future__ import annotations

import pytest

from shea.contracts.enums import ExecutionOutcome, FailureCategory
from shea.contracts.models import ToolExecutionRecord
from shea.recovery.classifier import FailureClassifier


@pytest.fixture
def classifier() -> FailureClassifier:
    return FailureClassifier()


def make_record(
    *,
    error: str | None,
    outcome: ExecutionOutcome = ExecutionOutcome.FAILURE,
) -> ToolExecutionRecord:
    return ToolExecutionRecord(
        id="execution-1",
        task_id="task-1",
        tool="test_tool",
        action="test_action",
        outcome=outcome,
        success=False,
        error=error,
    )


def test_timeout_is_retryable(classifier: FailureClassifier) -> None:
    result = classifier.classify(make_record(error="request timed out"))

    assert result.category is FailureCategory.TIMEOUT
    assert result.retryable is True
    assert result.recoverable is True
    assert result.security_relevant is False


def test_network_failure_is_retryable(classifier: FailureClassifier) -> None:
    result = classifier.classify(make_record(error="connection reset by peer"))

    assert result.category is FailureCategory.NETWORK
    assert result.retryable is True


def test_rate_limit_is_retryable(classifier: FailureClassifier) -> None:
    result = classifier.classify(make_record(error="HTTP 429 too many requests"))

    assert result.category is FailureCategory.RATE_LIMITED
    assert result.retryable is True


def test_permission_failure_is_not_retryable(
    classifier: FailureClassifier,
) -> None:
    result = classifier.classify(make_record(error="permission denied"))

    assert result.category is FailureCategory.AUTHORIZATION
    assert result.retryable is False
    assert result.security_relevant is True


def test_authentication_failure_is_not_blindly_retried(
    classifier: FailureClassifier,
) -> None:
    result = classifier.classify(make_record(error="invalid token"))

    assert result.category is FailureCategory.AUTHENTICATION
    assert result.retryable is False
    assert result.recoverable is True


def test_invalid_input_is_not_retryable(
    classifier: FailureClassifier,
) -> None:
    result = classifier.classify(make_record(error="invalid argument"))

    assert result.category is FailureCategory.INVALID_INPUT
    assert result.retryable is False
    assert result.recoverable is False


def test_security_failure_is_security_relevant(
    classifier: FailureClassifier,
) -> None:
    result = classifier.classify(
        make_record(error="security integrity violation")
    )

    assert result.category is FailureCategory.SECURITY
    assert result.retryable is False
    assert result.security_relevant is True


def test_unknown_outcome_requires_verification(
    classifier: FailureClassifier,
) -> None:
    result = classifier.classify(
        make_record(
            error=None,
            outcome=ExecutionOutcome.UNKNOWN,
        )
    )

    assert result.category is FailureCategory.UNKNOWN_OUTCOME
    assert result.retryable is False
    assert result.recoverable is True
    assert result.requires_verification is True


def test_unknown_failure_is_conservative(
    classifier: FailureClassifier,
) -> None:
    result = classifier.classify(
        make_record(error="something completely unexpected")
    )

    assert result.category is FailureCategory.UNKNOWN
    assert result.retryable is False
    assert result.requires_verification is True
    assert result.security_relevant is False