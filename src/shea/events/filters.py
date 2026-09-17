from __future__ import annotations

from dataclasses import dataclass

from .contracts import Event, EventPriority, priority_rank


def _pattern_matches(pattern: str, event_type: str) -> bool:
    """Return True if *pattern* matches *event_type*.

    Rules:
    - ``"*"`` matches everything.
    - ``"task.*"`` matches any event_type starting with ``"task."``.
    - Otherwise exact string match.
    """
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        prefix = pattern[:-1]  # "task." from "task.*"
        return event_type.startswith(prefix)
    return pattern == event_type


@dataclass(frozen=True)
class EventFilter:
    """Declarative filter combining multiple match criteria.

    All non-None fields must match for the filter to accept an event
    (logical AND). A ``None`` field means "don't filter on this axis".
    """

    event_types: frozenset[str] | None = None
    sources: frozenset[str] | None = None
    min_priority: EventPriority | None = None

    def matches(self, event: Event) -> bool:
        """Return True if *event* passes all configured criteria."""
        if self.event_types is not None:
            if not any(_pattern_matches(p, event.event_type) for p in self.event_types):
                return False
        if self.sources is not None:
            if event.source not in self.sources:
                return False
        if self.min_priority is not None:
            if priority_rank(event.priority) < priority_rank(self.min_priority):
                return False
        return True