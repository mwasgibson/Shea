from __future__ import annotations

from shea.provider.health import HealthTracker, ProviderHealthState


def test_empty_tracker_defaults_to_healthy() -> None:
    tracker = HealthTracker()
    assert tracker.state == ProviderHealthState.HEALTHY


def test_all_successes_is_healthy() -> None:
    tracker = HealthTracker()
    for _ in range(5):
        tracker.record_success()
    assert tracker.state == ProviderHealthState.HEALTHY


def test_moderate_failure_rate_is_degraded() -> None:
    tracker = HealthTracker(window_size=10, degraded_error_rate=0.3, unavailable_error_rate=0.7)
    for _ in range(6):
        tracker.record_success()
    for _ in range(4):
        tracker.record_failure()
    assert tracker.state == ProviderHealthState.DEGRADED


def test_high_failure_rate_is_unavailable() -> None:
    tracker = HealthTracker(window_size=10, degraded_error_rate=0.3, unavailable_error_rate=0.7)
    for _ in range(2):
        tracker.record_success()
    for _ in range(8):
        tracker.record_failure()
    assert tracker.state == ProviderHealthState.UNAVAILABLE


def test_window_slides_and_recovers() -> None:
    tracker = HealthTracker(window_size=5, degraded_error_rate=0.3, unavailable_error_rate=0.7)
    for _ in range(5):
        tracker.record_failure()
    assert tracker.state == ProviderHealthState.UNAVAILABLE

    for _ in range(5):
        tracker.record_success()
    assert tracker.state == ProviderHealthState.HEALTHY


def test_window_size_bounds_history() -> None:
    tracker = HealthTracker(window_size=3, degraded_error_rate=0.3, unavailable_error_rate=0.7)
    tracker.record_failure()
    tracker.record_failure()
    tracker.record_failure()
    # Push three successes through a window of 3 - failures should be
    # fully evicted, not just diluted.
    tracker.record_success()
    tracker.record_success()
    tracker.record_success()
    assert tracker.state == ProviderHealthState.HEALTHY