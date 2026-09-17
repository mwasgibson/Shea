from __future__ import annotations

import logging

from .contracts import Event, EventHandler, Subscription
from .filters import EventFilter, _pattern_matches  # pyright: ignore[reportPrivateUsage]
from .ports import EventSink

logger = logging.getLogger(__name__)


class EventBus:
    """Publish/subscribe event backbone for Shea's internal subsystems.

    Subscribers register a handler bound to an event-type pattern.
    When an event is published, all matching handlers are invoked
    synchronously in priority order.

    External sinks (``EventSink`` protocol) can be attached to forward
    every event to an external system (logs, metrics, WebSocket, etc.).
    Sinks optionally declare an ``EventFilter`` to limit what they see.
    """

    def __init__(self) -> None:
        self._subscriptions: list[Subscription] = []
        self._sinks: list[tuple[EventSink, EventFilter | None]] = []
        self._last_errors: list[tuple[str, Exception]] = []
        self._counter: int = 0

    # ── subscribe / unsubscribe ────────────────────────────────────

    def subscribe(
        self,
        event_pattern: str,
        handler: EventHandler,
        *,
        handler_priority: int = 0,
        subscription_id: str | None = None,
    ) -> str:
        """Register *handler* for events matching *event_pattern*.

        Returns the subscription ID (auto-generated if not provided).
        """
        self._counter += 1
        sub_id = subscription_id or f"sub-{self._counter}"
        sub = Subscription(
            id=sub_id,
            event_pattern=event_pattern,
            handler=handler,
            handler_priority=handler_priority,
        )
        self._subscriptions.append(sub)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove the subscription with *subscription_id*.

        Returns True if found and removed, False otherwise.
        """
        before = len(self._subscriptions)
        self._subscriptions = [s for s in self._subscriptions if s.id != subscription_id]
        return len(self._subscriptions) < before

    # ── sinks ──────────────────────────────────────────────────────

    def add_sink(self, sink: EventSink, *, event_filter: EventFilter | None = None) -> None:
        """Attach an external ``EventSink``.

        If *event_filter* is provided, the sink only receives events
        that pass the filter.
        """
        self._sinks.append((sink, event_filter))

    # ── publish ────────────────────────────────────────────────────

    def publish(self, event: Event) -> None:
        """Dispatch *event* to all matching handlers and sinks.

        Handler errors are caught, logged, and collected in
        ``last_errors`` — they never propagate to the publisher.
        """
        self._last_errors.clear()

        # Collect matching subscriptions.
        matched = [
            s for s in self._subscriptions
            if _pattern_matches(s.event_pattern, event.event_type)
        ]
        # Sort by handler_priority descending, then by registration order (stable sort).
        matched.sort(key=lambda s: s.handler_priority, reverse=True)

        for sub in matched:
            try:
                sub.handler(event)
            except Exception as exc:
                logger.warning(
                    "Event handler %r failed for %s: %s",
                    sub.id,
                    event.event_type,
                    exc,
                )
                self._last_errors.append((sub.id, exc))

        # Forward to sinks.
        for sink, filt in self._sinks:
            if filt is not None and not filt.matches(event):
                continue
            try:
                sink.accept(event)
            except Exception as exc:
                logger.warning(
                    "Event sink %r failed for %s: %s",
                    type(sink).__name__,
                    event.event_type,
                    exc,
                )
                self._last_errors.append((type(sink).__name__, exc))

    # ── introspection ──────────────────────────────────────────────

    @property
    def last_errors(self) -> list[tuple[str, Exception]]:
        """Errors from the most recent ``publish()`` call."""
        return list(self._last_errors)

    @property
    def subscription_count(self) -> int:
        return len(self._subscriptions)

    def subscriptions_for(self, event_type: str) -> list[Subscription]:
        """Return subscriptions that would match *event_type*."""
        return [
            s for s in self._subscriptions
            if _pattern_matches(s.event_pattern, event_type)
        ]