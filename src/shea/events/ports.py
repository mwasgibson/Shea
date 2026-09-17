from __future__ import annotations

from typing import Protocol

from .contracts import Event


class EventSink(Protocol):
    """An external consumer that receives published events.

    Sinks are registered on the ``EventBus`` and receive every event
    that passes their optional filter.  Use cases include forwarding
    events to a log file, metrics collector, WebSocket stream, or
    external message broker.

    Implementations must be safe to call synchronously on the
    publishing thread.
    """

    def accept(self, event: Event) -> None:  # pragma: no cover
        ...