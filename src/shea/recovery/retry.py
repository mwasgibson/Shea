from __future__ import annotations

import random

from shea.contracts.models import RetryPolicy


class RetryController:
    """Calculates bounded retry delays."""

    def __init__(self, policy: RetryPolicy | None = None) -> None:
        self._policy = policy or RetryPolicy()

    @property
    def max_attempts(self) -> int:
        return self._policy.max_attempts

    def can_retry(self, attempts_made: int) -> bool:
        return attempts_made < self._policy.max_attempts

    def delay_for(self, attempt_number: int) -> float:
        if attempt_number < 1:
            raise ValueError("attempt_number must be >= 1")

        if self._policy.exponential_backoff:
            delay = self._policy.initial_delay_seconds * (2 ** (attempt_number - 1))
        else:
            delay = self._policy.initial_delay_seconds

        delay = min(delay, self._policy.max_delay_seconds)

        if self._policy.jitter:
            delay *= random.uniform(0.5, 1.5)

        return float(min(delay, self._policy.max_delay_seconds))