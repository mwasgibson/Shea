from __future__ import annotations

from shea.contracts.models import RetryPolicy
from shea.recovery.retry import RetryController


def test_retry_allowed_before_limit() -> None:
    controller = RetryController(
        RetryPolicy(max_attempts=3)
    )
    assert controller.can_retry(0) is True
    assert controller.can_retry(1) is True
    assert controller.can_retry(2) is True

def test_retry_denied_at_limit() -> None:
    controller = RetryController(
        RetryPolicy(max_attempts=3)
    )
    assert controller.can_retry(3) is False
    assert controller.can_retry(4) is False

def test_exponential_backoff_increases() -> None:
    controller = RetryController(
        RetryPolicy(
            initial_delay_seconds=1.0,
            max_delay_seconds=60.0,
            exponential_backoff=True,
            jitter=False,
        )
    )
    assert controller.delay_for(1) == 1.0
    assert controller.delay_for(2) == 2.0
    assert controller.delay_for(3) == 4.0
    assert controller.delay_for(4) == 8.0

def test_backoff_is_capped() -> None:
    controller = RetryController(
        RetryPolicy(
            initial_delay_seconds=10.0,
            max_delay_seconds=15.0,
            exponential_backoff=True,
            jitter=False,
        )
    )

    assert controller.delay_for(1) == 10.0
    assert controller.delay_for(2) == 15.0
    assert controller.delay_for(3) == 15.0


def test_linear_delay_when_exponential_backoff_disabled() -> None:
    controller = RetryController(
        RetryPolicy(
            initial_delay_seconds=5.0,
            max_delay_seconds=60.0,
            exponential_backoff=False,
            jitter=False,
        )
    )
    assert controller.delay_for(1) == 5.0
    assert controller.delay_for(2) == 5.0
    assert controller.delay_for(3) == 5.0

def test_invalid_attempt_number_raises() -> None:
    controller = RetryController()

    try:
        controller.delay_for(0)
    except ValueError as exc:
        assert "attempt_number" in str(exc)
    else:
        raise AssertionError("Expected ValueError")