from __future__ import annotations

from datetime import UTC, datetime

from shea.events.bus import EventBus
from shea.events.contracts import Event, EventPriority


def _make_event(
    event_type: str = "test.event",
    source: str = "test",
    priority: EventPriority = EventPriority.NORMAL,
    correlation_id: str | None = None,
) -> Event:
    return Event(
        event_id="evt-1",
        event_type=event_type,
        source=source,
        timestamp=datetime.now(UTC),
        payload={"key": "value"},
        correlation_id=correlation_id,
        priority=priority,
    )


class TestSubscribeAndPublish:
    def test_handler_receives_matching_event(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("test.event", received.append)

        event = _make_event()
        bus.publish(event)

        assert len(received) == 1
        assert received[0] is event

    def test_handler_not_called_for_non_matching_event(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("task.created", received.append)

        bus.publish(_make_event(event_type="security.violation"))

        assert received == []

    def test_wildcard_star_matches_everything(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("*", received.append)

        bus.publish(_make_event(event_type="task.created"))
        bus.publish(_make_event(event_type="security.violation"))

        assert len(received) == 2

    def test_prefix_wildcard_matches_namespace(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("task.*", received.append)

        bus.publish(_make_event(event_type="task.created"))
        bus.publish(_make_event(event_type="task.state_changed"))
        bus.publish(_make_event(event_type="security.violation"))

        assert len(received) == 2

    def test_exact_match_does_not_match_prefix(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("task", received.append)

        bus.publish(_make_event(event_type="task.created"))

        assert received == []

    def test_multiple_handlers_all_receive(self):
        bus = EventBus()
        received_a: list[Event] = []
        received_b: list[Event] = []
        bus.subscribe("test.event", received_a.append)
        bus.subscribe("test.event", received_b.append)

        bus.publish(_make_event())

        assert len(received_a) == 1
        assert len(received_b) == 1


class TestHandlerOrdering:
    def test_higher_priority_handlers_run_first(self):
        bus = EventBus()
        order: list[str] = []

        bus.subscribe("test.event", lambda e: order.append("low"), handler_priority=0)
        bus.subscribe("test.event", lambda e: order.append("high"), handler_priority=10)
        bus.subscribe("test.event", lambda e: order.append("mid"), handler_priority=5)

        bus.publish(_make_event())

        assert order == ["high", "mid", "low"]

    def test_same_priority_uses_registration_order(self):
        bus = EventBus()
        order: list[str] = []

        bus.subscribe("test.event", lambda e: order.append("first"), handler_priority=0)
        bus.subscribe("test.event", lambda e: order.append("second"), handler_priority=0)
        bus.subscribe("test.event", lambda e: order.append("third"), handler_priority=0)

        bus.publish(_make_event())

        assert order == ["first", "second", "third"]


class TestErrorIsolation:
    def test_failing_handler_does_not_block_others(self):
        bus = EventBus()
        received: list[Event] = []

        def failing_handler(event: Event) -> None:
            raise ValueError("boom")

        bus.subscribe("test.event", failing_handler, handler_priority=10)
        bus.subscribe("test.event", received.append, handler_priority=0)

        bus.publish(_make_event())

        assert len(received) == 1

    def test_errors_are_recorded(self):
        bus = EventBus()

        def failing_handler(event: Event) -> None:
            raise RuntimeError("oops")

        sub_id = bus.subscribe("test.event", failing_handler, subscription_id="bad-handler")
        assert sub_id

        bus.publish(_make_event())

        assert len(bus.last_errors) == 1
        assert bus.last_errors[0][0] == "bad-handler"
        assert isinstance(bus.last_errors[0][1], RuntimeError)

    def test_errors_cleared_on_next_publish(self):
        bus = EventBus()
        bus.subscribe("test.event", lambda e: (_ for _ in ()).throw(ValueError("fail")))

        bus.publish(_make_event())
        assert len(bus.last_errors) == 1

        bus.publish(_make_event(event_type="other.event"))
        assert len(bus.last_errors) == 0


class TestUnsubscribe:
    def test_unsubscribe_removes_handler(self):
        bus = EventBus()
        received: list[Event] = []
        sub_id = bus.subscribe("test.event", received.append)

        bus.publish(_make_event())
        assert len(received) == 1

        result = bus.unsubscribe(sub_id)
        assert result is True

        bus.publish(_make_event())
        assert len(received) == 1  # no new events

    def test_unsubscribe_nonexistent_returns_false(self):
        bus = EventBus()
        assert bus.unsubscribe("nonexistent") is False

    def test_subscription_count(self):
        bus = EventBus()
        bus.subscribe("a", lambda e: None)
        bus.subscribe("b", lambda e: None)
        assert bus.subscription_count == 2


class TestSinks:
    def test_sink_receives_all_events(self):
        bus = EventBus()
        sink_events: list[Event] = []

        class ListSink:
            def accept(self, event: Event) -> None:
                sink_events.append(event)

        bus.add_sink(ListSink())

        bus.publish(_make_event(event_type="task.created"))
        bus.publish(_make_event(event_type="security.violation"))

        assert len(sink_events) == 2

    def test_sink_with_filter(self):
        from shea.events.filters import EventFilter

        bus = EventBus()
        sink_events: list[Event] = []

        class ListSink:
            def accept(self, event: Event) -> None:
                sink_events.append(event)

        bus.add_sink(
            ListSink(),
            event_filter=EventFilter(min_priority=EventPriority.HIGH),
        )

        bus.publish(_make_event(priority=EventPriority.NORMAL))
        bus.publish(_make_event(priority=EventPriority.HIGH))
        bus.publish(_make_event(priority=EventPriority.CRITICAL))

        assert len(sink_events) == 2

    def test_failing_sink_does_not_break_dispatch(self):
        bus = EventBus()
        received: list[Event] = []

        class BrokenSink:
            def accept(self, event: Event) -> None:
                raise RuntimeError("sink error")

        bus.add_sink(BrokenSink())
        bus.subscribe("test.event", received.append)

        bus.publish(_make_event())

        assert len(received) == 1
        assert len(bus.last_errors) == 1


class TestIntrospection:
    def test_subscriptions_for(self):
        bus = EventBus()
        bus.subscribe("task.*", lambda e: None, subscription_id="task-watcher")
        bus.subscribe("security.*", lambda e: None, subscription_id="sec-watcher")

        matches = bus.subscriptions_for("task.created")
        assert len(matches) == 1
        assert matches[0].id == "task-watcher"