from __future__ import annotations


class NoEligibleProviderError(Exception):
    """Raised when no registered provider satisfies the current routing
    requirements — before any provider is even attempted. Distinct from
    AllProvidersExhaustedError: this means the request was never sent to
    anyone, not that everyone who was tried failed.
    """


class AllProvidersExhaustedError(Exception):
    """Raised when every eligible provider was attempted and all failed.

    Carries the ordered list of (provider_id, failure_category) so a
    caller can see exactly what was tried and why, without a second
    round-trip to the audit log.
    """

    def __init__(self, attempts: list[tuple[str, str]]) -> None:
        self.attempts = attempts
        super().__init__(f"All eligible providers failed: {attempts}")