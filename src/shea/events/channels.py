"""Typed event channels for Shea subsystems.

Each channel is a thin convenience wrapper that constructs correctly-typed
``Event`` instances and publishes them through the ``EventBus``.  Channels
are intentionally stateless — they receive the bus, clock, and ID
generator at construction and delegate all dispatch to the bus.

Channels enforce consistent ``event_type`` namespacing and ``source``
attribution so that subscribers can rely on stable event schemas.
"""

from __future__ import annotations

from typing import Any

from shea.contracts.enums import (
    ExecutionOutcome,
    TaskState,
)
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator

from .bus import EventBus
from .contracts import Event, EventPriority


class TaskChannel:
    """Events emitted by the core orchestrator during task lifecycle."""

    def __init__(self, bus: EventBus, clock: Clock, id_generator: IdGenerator) -> None:
        self._bus = bus
        self._clock = clock
        self._ids = id_generator

    def _emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        correlation_id: str | None = None,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> None:
        self._bus.publish(
            Event(
                event_id=self._ids.new_id(),
                event_type=event_type,
                source="orchestrator",
                timestamp=self._clock.now(),
                payload=payload,
                correlation_id=correlation_id,
                priority=priority,
            )
        )

    def created(
        self,
        task_id: str,
        session_id: str,
        request_id: str,
    ) -> None:
        self._emit(
            "task.created",
            {"task_id": task_id, "session_id": session_id},
            correlation_id=request_id,
        )

    def state_changed(
        self,
        task_id: str,
        from_state: TaskState,
        to_state: TaskState,
        event: str,
        *,
        request_id: str | None = None,
    ) -> None:
        self._emit(
            "task.state_changed",
            {
                "task_id": task_id,
                "from_state": from_state.value,
                "to_state": to_state.value,
                "trigger": event,
            },
            correlation_id=request_id,
        )

    def plan_attached(
        self,
        task_id: str,
        plan_id: str,
        *,
        request_id: str | None = None,
    ) -> None:
        self._emit(
            "task.plan_attached",
            {"task_id": task_id, "plan_id": plan_id},
            correlation_id=request_id,
        )


class SecurityChannel:
    """Events emitted by the security subsystem."""

    def __init__(self, bus: EventBus, clock: Clock, id_generator: IdGenerator) -> None:
        self._bus = bus
        self._clock = clock
        self._ids = id_generator

    def _emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        correlation_id: str | None = None,
        priority: EventPriority = EventPriority.HIGH,
    ) -> None:
        self._bus.publish(
            Event(
                event_id=self._ids.new_id(),
                event_type=event_type,
                source="security_service",
                timestamp=self._clock.now(),
                payload=payload,
                correlation_id=correlation_id,
                priority=priority,
            )
        )

    def violation(
        self,
        task_id: str,
        tool: str,
        category: str,
        reason: str,
        *,
        request_id: str | None = None,
    ) -> None:
        self._emit(
            "security.violation",
            {
                "task_id": task_id,
                "tool": tool,
                "category": category,
                "reason": reason,
            },
            correlation_id=request_id,
            priority=EventPriority.CRITICAL,
        )

    def injection_detected(
        self,
        task_id: str,
        tool: str,
        matched_phrases: list[str],
        *,
        halted: bool = False,
        request_id: str | None = None,
    ) -> None:
        self._emit(
            "security.injection_detected",
            {
                "task_id": task_id,
                "tool": tool,
                "matched_phrases": matched_phrases,
                "halted": halted,
            },
            correlation_id=request_id,
            priority=EventPriority.CRITICAL if halted else EventPriority.HIGH,
        )

    def request_cleared(
        self,
        task_id: str,
        tool: str,
        *,
        request_id: str | None = None,
    ) -> None:
        self._emit(
            "security.request_cleared",
            {"task_id": task_id, "tool": tool},
            correlation_id=request_id,
            priority=EventPriority.LOW,
        )


class ExecutionChannel:
    """Events emitted by the execution subsystem."""

    def __init__(self, bus: EventBus, clock: Clock, id_generator: IdGenerator) -> None:
        self._bus = bus
        self._clock = clock
        self._ids = id_generator

    def _emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        correlation_id: str | None = None,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> None:
        self._bus.publish(
            Event(
                event_id=self._ids.new_id(),
                event_type=event_type,
                source="execution_service",
                timestamp=self._clock.now(),
                payload=payload,
                correlation_id=correlation_id,
                priority=priority,
            )
        )

    def started(
        self,
        task_id: str,
        tool: str,
        action: str,
        *,
        request_id: str | None = None,
    ) -> None:
        self._emit(
            "execution.started",
            {"task_id": task_id, "tool": tool, "action": action},
            correlation_id=request_id,
        )

    def completed(
        self,
        task_id: str,
        tool: str,
        outcome: ExecutionOutcome,
        *,
        request_id: str | None = None,
    ) -> None:
        self._emit(
            "execution.completed",
            {"task_id": task_id, "tool": tool, "outcome": outcome.value},
            correlation_id=request_id,
        )

    def idempotency_hit(
        self,
        task_id: str,
        tool: str,
        idempotency_key: str,
        *,
        request_id: str | None = None,
    ) -> None:
        self._emit(
            "execution.idempotency_hit",
            {"task_id": task_id, "tool": tool, "idempotency_key": idempotency_key},
            correlation_id=request_id,
        )


class ProviderChannel:
    """Events emitted by the provider routing subsystem."""

    def __init__(self, bus: EventBus, clock: Clock, id_generator: IdGenerator) -> None:
        self._bus = bus
        self._clock = clock
        self._ids = id_generator

    def _emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        correlation_id: str | None = None,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> None:
        self._bus.publish(
            Event(
                event_id=self._ids.new_id(),
                event_type=event_type,
                source="provider_routing",
                timestamp=self._clock.now(),
                payload=payload,
                correlation_id=correlation_id,
                priority=priority,
            )
        )

    def selected(
        self,
        provider_id: str,
        model_id: str,
    ) -> None:
        self._emit(
            "provider.selected",
            {"provider_id": provider_id, "model_id": model_id},
        )

    def failover(
        self,
        from_provider: str,
        to_provider: str,
        reason: str,
    ) -> None:
        self._emit(
            "provider.failover",
            {
                "from_provider": from_provider,
                "to_provider": to_provider,
                "reason": reason,
            },
            priority=EventPriority.HIGH,
        )

    def exhausted(
        self,
        attempted_providers: list[str],
    ) -> None:
        self._emit(
            "provider.exhausted",
            {"attempted_providers": attempted_providers},
            priority=EventPriority.CRITICAL,
        )