from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ProviderHealthState(StrEnum):
    """Research doc Section 8.8/8.16: derived from real outcomes, not a
    provider's self-report ("health check success shouldn't override
    actual request failures... real workload behavior is more meaningful
    than a provider saying 'I'm totally fine'" — Section 8.18).
    """

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class HealthTracker:
    """A bounded sliding window of recent outcomes, deriving health state
    from the observed error rate within that window.

    KNOWN SIMPLIFICATION: no exponential backoff, no gradual traffic
    recovery percentages (research doc Section 8.17's "5% -> 25% -> 50%
    -> 100%"). A provider recovers to HEALTHY as soon as enough recent
    successes push the window's error rate back down — this is the
    doc's own acknowledged fallback: "For V1, even a simpler cooldown
    plus health-check mechanism is enough." Gradual/weighted recovery is
    a real future improvement, not implemented here.
    """

    window_size: int = 10
    degraded_error_rate: float = 0.3
    unavailable_error_rate: float = 0.7
    _outcomes: list[bool] = field(default_factory=lambda: list())

    def record_success(self) -> None:
        self._record(True)

    def record_failure(self) -> None:
        self._record(False)

    def _record(self, succeeded: bool) -> None:
        self._outcomes.append(succeeded)
        if len(self._outcomes) > self.window_size:
            self._outcomes.pop(0)

    @property
    def state(self) -> ProviderHealthState:
        if not self._outcomes:
            # No data yet: optimistic default. A real deployment might
            # prefer a lightweight startup health_check() call instead
            # (Section 8.18) before the first real request — deferred.
            return ProviderHealthState.HEALTHY

        error_rate = 1.0 - (sum(self._outcomes) / len(self._outcomes))
        if error_rate >= self.unavailable_error_rate:
            return ProviderHealthState.UNAVAILABLE
        if error_rate >= self.degraded_error_rate:
            return ProviderHealthState.DEGRADED
        return ProviderHealthState.HEALTHY