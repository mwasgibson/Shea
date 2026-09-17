"""Tests for EventFilter: type matching, source matching, priority filtering."""

from __future__ import annotations

from datetime import UTC, datetime

from shea.events.contracts import Event, EventPriority
from shea.events.filters import EventFilter, _pattern_matches  # pyright: ignore[reportPrivateUsage]


def _evt(
    event_type: str = "test.event",
    source: str = "test",
    priority: EventPriority = EventPriority.NORMAL,
) -> Event:
    return Event(
        event_id="e-1",
        event_type=event_type,
        source=source,
        timestamp=datetime.now(UTC),
        priority=priority,
    )


class TestPatternMatching:
    def test_exact_match(self):
        assert _pattern_matches("task.created", "task.created")

    def test_exact_mismatch(self):
        assert not _pattern_matches("task.created", "task.failed")

    def test_global_wildcard(self):
        assert _pattern_matches("*", "anything.here")

    def test_prefix_wildcard_match(self):
        assert _pattern_matches("task.*", "task.created")
        assert _pattern_matches("task.*", "task.state_changed")

    def test_prefix_wildcard_no_match(self):
        assert not _pattern_matches("task.*", "security.violation")

    def test_prefix_wildcard_requires_dot(self):
        # "task.*" should match "task.X" but the pattern "task.*" means
        # prefix "task." — so "taskX" should not match.
        assert not _pattern_matches("task.*", "taskX")


class TestEventFilter:
    def test_empty_filter_matches_all(self):
        f = EventFilter()
        assert f.matches(_evt())

    def test_event_type_filter_exact(self):
        f = EventFilter(event_types=frozenset({"task.created"}))
        assert f.matches(_evt(event_type="task.created"))
        assert not f.matches(_evt(event_type="task.failed"))

    def test_event_type_filter_wildcard(self):
        f = EventFilter(event_types=frozenset({"task.*"}))
        assert f.matches(_evt(event_type="task.created"))
        assert f.matches(_evt(event_type="task.state_changed"))
        assert not f.matches(_evt(event_type="security.violation"))

    def test_event_type_filter_multiple_patterns(self):
        f = EventFilter(event_types=frozenset({"task.*", "security.*"}))
        assert f.matches(_evt(event_type="task.created"))
        assert f.matches(_evt(event_type="security.violation"))
        assert not f.matches(_evt(event_type="execution.started"))

    def test_source_filter(self):
        f = EventFilter(sources=frozenset({"orchestrator"}))
        assert f.matches(_evt(source="orchestrator"))
        assert not f.matches(_evt(source="security_service"))

    def test_min_priority_filter(self):
        f = EventFilter(min_priority=EventPriority.HIGH)
        assert f.matches(_evt(priority=EventPriority.HIGH))
        assert f.matches(_evt(priority=EventPriority.CRITICAL))
        assert not f.matches(_evt(priority=EventPriority.NORMAL))
        assert not f.matches(_evt(priority=EventPriority.LOW))

    def test_combined_filters_all_must_pass(self):
        f = EventFilter(
            event_types=frozenset({"task.*"}),
            sources=frozenset({"orchestrator"}),
            min_priority=EventPriority.HIGH,
        )
        # Passes all three
        assert f.matches(_evt(
            event_type="task.created",
            source="orchestrator",
            priority=EventPriority.CRITICAL,
        ))
        # Fails event_type
        assert not f.matches(_evt(
            event_type="security.violation",
            source="orchestrator",
            priority=EventPriority.CRITICAL,
        ))
        # Fails source
        assert not f.matches(_evt(
            event_type="task.created",
            source="security_service",
            priority=EventPriority.CRITICAL,
        ))
        # Fails priority
        assert not f.matches(_evt(
            event_type="task.created",
            source="orchestrator",
            priority=EventPriority.LOW,
        ))