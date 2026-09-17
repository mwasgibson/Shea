from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EventPriority(StrEnum):
    """Dispatch priority — higher-priority handlers run first."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# Numeric ordering for comparisons (higher = more urgent).
_PRIORITY_ORDER: dict[EventPriority, int] = {
    EventPriority.LOW: 0,
    EventPriority.NORMAL: 1,
    EventPriority.HIGH: 2,
    EventPriority.CRITICAL: 3,
}


def priority_rank(priority: EventPriority) -> int:
    """Return a numeric rank for *priority* (higher = more urgent)."""
    return _PRIORITY_ORDER.get(priority, 1)


@dataclass(frozen=True)
class Event:
    """A single event emitted through the bus.

    ``event_type`` uses dot-delimited namespaces, e.g.
    ``"task.state_changed"``, ``"security.violation"``.

    ``correlation_id`` ties related events together across subsystems
    (typically the originating ``request_id`` or ``task_id``).
    """

    event_id: str
    event_type: str
    source: str
    timestamp: datetime
    payload: dict[str, Any] = field(default_factory=dict[str, Any])
    correlation_id: str | None = None
    priority: EventPriority = EventPriority.NORMAL


# A handler is a simple callable that receives an Event.
EventHandler = Callable[[Event], None]


@dataclass(frozen=True)
class Subscription:
    """A registered handler bound to an event-type pattern.

    ``event_pattern`` supports:
    - Exact match: ``"task.state_changed"``
    - Prefix wildcard: ``"task.*"`` (matches any event starting with ``"task."``)
    - Global wildcard: ``"*"`` (matches everything)

    ``handler_priority`` controls dispatch order within a single event:
    higher values run first (descending).
    """

    id: str
    event_pattern: str
    handler: EventHandler
    handler_priority: int = 0