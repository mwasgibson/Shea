from __future__ import annotations

from typing import Any

from shea.contracts.models import AuditEvent
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.repositories import AuditSink


class AuditRecorder:
    """Every subsystem should have nothing to do to get audited except
    call `record()` here — event_id/timestamp generation is centralized
    so no call site can produce a malformed or unstamped AuditEvent.

    Built now, in Phase 1, before there's anything risky to audit yet, so
    later subsystems (Decision, Execution, Security) inherit a working
    audit path instead of bolting one on after the fact.
    """

    def __init__(self, sink: AuditSink, clock: Clock, id_generator: IdGenerator) -> None:
        self._sink = sink
        self._clock = clock
        self._id_generator = id_generator

    def record(
        self,
        *,
        actor: str,
        component: str,
        event_type: str,
        action: str,
        result: str,
        request_id: str | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=self._id_generator.new_id(),
            request_id=request_id,
            task_id=task_id,
            timestamp=self._clock.now(),
            actor=actor,
            component=component,
            event_type=event_type,
            action=action,
            result=result,
            metadata=metadata or {},
        )
        self._sink.record(event)
        return event