from __future__ import annotations

from typing import Any

from shea.contracts.models import AuditEvent
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.redactor import Redactor
from shea.ports.repositories import AuditSink


class AuditRecorder:
    def __init__(
        self,
        sink: AuditSink,
        clock: Clock,
        id_generator: IdGenerator,
        redactor: Redactor | None = None,
    ) -> None:
        self._sink = sink
        self._clock = clock
        self._id_generator = id_generator
        self._redactor = redactor

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
        sequence_number: int | None = None,
        prev_hash: str | None = None,
        event_hash: str | None = None,
    ) -> AuditEvent:
        safe_metadata = metadata or {}
        if self._redactor is not None:
            safe_metadata = self._redactor.redact_mapping(safe_metadata)

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
            metadata=safe_metadata,
            sequence_number=sequence_number if sequence_number is not None else 0,
            prev_hash=prev_hash,
            event_hash=event_hash,
        )
        # Delegate persistence, hashing, and sequence numbering completely to sink
        self._sink.record(event)
        return event