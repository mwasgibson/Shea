from __future__ import annotations

from datetime import UTC, datetime

from shea.contracts.enums import ExecutionOutcome, TaskState
from shea.events.bus import EventBus
from shea.events.channels import (
    ExecutionChannel,
    ProviderChannel,
    SecurityChannel,
    TaskChannel,
)
from shea.events.contracts import Event, EventPriority


class FakeClock:
    def now(self) -> datetime:
        return datetime(2025, 1, 1, tzinfo=UTC)


class FakeIdGenerator:
    def __init__(self):
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"id-{self._counter}"


def _collect(bus: EventBus) -> list[Event]:
    collected: list[Event] = []
    bus.subscribe("*", collected.append)
    return collected


class TestTaskChannel:
    def test_created(self):
        bus = EventBus()
        events = _collect(bus)
        ch = TaskChannel(bus, FakeClock(), FakeIdGenerator())

        ch.created("task-1", "session-1", "req-1")

        assert len(events) == 1
        e = events[0]
        assert e.event_type == "task.created"
        assert e.source == "orchestrator"
        assert e.payload["task_id"] == "task-1"
        assert e.payload["session_id"] == "session-1"
        assert e.correlation_id == "req-1"

    def test_state_changed(self):
        bus = EventBus()
        events = _collect(bus)
        ch = TaskChannel(bus, FakeClock(), FakeIdGenerator())

        ch.state_changed(
            "task-1", TaskState.CREATED, TaskState.PLANNING, "start_planning",
            request_id="req-1",
        )

        assert len(events) == 1
        e = events[0]
        assert e.event_type == "task.state_changed"
        assert e.payload["from_state"] == "CREATED"
        assert e.payload["to_state"] == "PLANNING"
        assert e.payload["trigger"] == "start_planning"

    def test_plan_attached(self):
        bus = EventBus()
        events = _collect(bus)
        ch = TaskChannel(bus, FakeClock(), FakeIdGenerator())

        ch.plan_attached("task-1", "plan-1", request_id="req-1")

        assert len(events) == 1
        e = events[0]
        assert e.event_type == "task.plan_attached"
        assert e.payload["plan_id"] == "plan-1"


class TestSecurityChannel:
    def test_violation(self):
        bus = EventBus()
        events = _collect(bus)
        ch = SecurityChannel(bus, FakeClock(), FakeIdGenerator())

        ch.violation("task-1", "http.fetch", "ssrf", "private IP", request_id="req-1")

        assert len(events) == 1
        e = events[0]
        assert e.event_type == "security.violation"
        assert e.priority == EventPriority.CRITICAL
        assert e.payload["category"] == "ssrf"

    def test_injection_detected(self):
        bus = EventBus()
        events = _collect(bus)
        ch = SecurityChannel(bus, FakeClock(), FakeIdGenerator())

        ch.injection_detected(
            "task-1", "filesystem.read", ["ignore previous"],
            halted=True, request_id="req-1",
        )

        assert len(events) == 1
        e = events[0]
        assert e.event_type == "security.injection_detected"
        assert e.payload["halted"] is True
        assert e.priority == EventPriority.CRITICAL

    def test_injection_detected_not_halted_is_high_priority(self):
        bus = EventBus()
        events = _collect(bus)
        ch = SecurityChannel(bus, FakeClock(), FakeIdGenerator())

        ch.injection_detected("task-1", "fs.read", ["test"], halted=False)

        assert events[0].priority == EventPriority.HIGH

    def test_request_cleared(self):
        bus = EventBus()
        events = _collect(bus)
        ch = SecurityChannel(bus, FakeClock(), FakeIdGenerator())

        ch.request_cleared("task-1", "filesystem.read", request_id="req-1")

        assert len(events) == 1
        assert events[0].event_type == "security.request_cleared"
        assert events[0].priority == EventPriority.LOW


class TestExecutionChannel:
    def test_started(self):
        bus = EventBus()
        events = _collect(bus)
        ch = ExecutionChannel(bus, FakeClock(), FakeIdGenerator())

        ch.started("task-1", "filesystem.write", "write", request_id="req-1")

        assert len(events) == 1
        e = events[0]
        assert e.event_type == "execution.started"
        assert e.payload["tool"] == "filesystem.write"

    def test_completed(self):
        bus = EventBus()
        events = _collect(bus)
        ch = ExecutionChannel(bus, FakeClock(), FakeIdGenerator())

        ch.completed("task-1", "filesystem.write", ExecutionOutcome.SUCCESS)

        assert events[0].event_type == "execution.completed"
        assert events[0].payload["outcome"] == "SUCCESS"

    def test_idempotency_hit(self):
        bus = EventBus()
        events = _collect(bus)
        ch = ExecutionChannel(bus, FakeClock(), FakeIdGenerator())

        ch.idempotency_hit("task-1", "filesystem.write", "key-abc")

        assert events[0].event_type == "execution.idempotency_hit"
        assert events[0].payload["idempotency_key"] == "key-abc"


class TestProviderChannel:
    def test_selected(self):
        bus = EventBus()
        events = _collect(bus)
        ch = ProviderChannel(bus, FakeClock(), FakeIdGenerator())

        ch.selected("ghost", "ghost-x1(openai)")

        assert events[0].event_type == "provider.selected"
        assert events[0].payload["provider_id"] == "ghost"

    def test_failover(self):
        bus = EventBus()
        events = _collect(bus)
        ch = ProviderChannel(bus, FakeClock(), FakeIdGenerator())

        ch.failover("ghost", "ollama", "timeout")

        assert events[0].event_type == "provider.failover"
        assert events[0].priority == EventPriority.HIGH

    def test_exhausted(self):
        bus = EventBus()
        events = _collect(bus)
        ch = ProviderChannel(bus, FakeClock(), FakeIdGenerator())

        ch.exhausted(["ghost", "ollama"])

        assert events[0].event_type == "provider.exhausted"
        assert events[0].priority == EventPriority.CRITICAL
        assert events[0].payload["attempted_providers"] == ["ghost", "ollama"]