from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from shea.contracts.models import Intent, ModelResponse, Request
from shea.events.bus import EventBus
from shea.events.channels import InteractionChannel
from shea.events.contracts import Event
from shea.memory.contracts import MemoryProposal, MemoryType
from shea.memory.extractor import MemoryExtractor
from shea.model.scripted import ScriptedModelProvider
from shea.persistence.sqlite.intent_repository import SqliteIntentRepository
from shea.persistence.sqlite.request_repository import SqliteRequestRepository
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


class _Broker:
    def __init__(self) -> None:
        self.proposals: list[MemoryProposal] = []

    def propose(self, proposal: MemoryProposal) -> None:
        self.proposals.append(proposal)


class _NoTools:
    def list_by_task(self, task_id: str) -> list[object]:
        return []


def _memories(*contents: str) -> ModelResponse:
    return ModelResponse(
        content="",
        structured_data={"memories": [{"type": "PREFERENCE", "content": c} for c in contents]},
    )


def _build(
    conn: sqlite3.Connection, unit_of_work: SqliteUnitOfWork, model: ScriptedModelProvider
) -> tuple[EventBus, _Broker, SqliteRequestRepository, SqliteIntentRepository]:
    bus = EventBus()
    broker = _Broker()
    requests = SqliteRequestRepository(conn, unit_of_work=unit_of_work)
    intents = SqliteIntentRepository(conn, unit_of_work=unit_of_work)
    MemoryExtractor(
        event_bus=bus,
        memory_broker=broker,  # type: ignore[arg-type]
        intent_repository=intents,
        request_repository=requests,
        tool_execution_repository=_NoTools(),  # type: ignore[arg-type]
        model_provider=model,
    )
    return bus, broker, requests, intents


def _request(request_id: str, *, profile_id: str, response: str | None = None) -> Request:
    return Request(
        request_id=request_id,
        session_id="s",
        actor="user",
        input="I always want answers in JSON",
        source="text",
        created_at=NOW,
        profile_id=profile_id,
        response=response,
    )


def test_conversation_turn_extracts_memory_without_any_task(
    conn: sqlite3.Connection, unit_of_work: SqliteUnitOfWork
) -> None:
    model = ScriptedModelProvider()
    model.queue_response(_memories("prefers JSON answers"))
    bus, broker, requests, _ = _build(conn, unit_of_work, model)
    requests.save(_request("req-1", profile_id="work", response="Noted."))

    class _Clock:
        def now(self) -> datetime:
            return NOW

    class _Ids:
        def new_id(self) -> str:
            return "evt-1"

    InteractionChannel(bus, _Clock(), _Ids()).conversation_turn(  # type: ignore[arg-type]
        request_id="req-1", session_id="s"
    )

    assert len(broker.proposals) == 1
    proposal = broker.proposals[0]
    assert proposal.content == "prefers JSON answers"
    assert proposal.type is MemoryType.PREFERENCE
    assert proposal.profile_id == "work"  # taken from the Request
    assert proposal.request_id == "req-1"
    assert proposal.task_id is None


def test_conversation_turn_without_a_recorded_reply_extracts_nothing(
    conn: sqlite3.Connection, unit_of_work: SqliteUnitOfWork
) -> None:
    model = ScriptedModelProvider()
    bus, broker, requests, _ = _build(conn, unit_of_work, model)
    requests.save(_request("req-1", profile_id="work", response=None))

    bus.publish(
        Event(
            event_id="e",
            event_type="interaction.conversation_turn",
            source="interaction",
            timestamp=NOW,
            payload={"request_id": "req-1", "session_id": "s"},
        )
    )
    assert broker.proposals == []


def _complete_task_event(task_id: str) -> Event:
    return Event(
        event_id="e",
        event_type="task.state_changed",
        source="task",
        timestamp=NOW,
        payload={"to_state": "COMPLETED", "task_id": task_id},
        correlation_id="req-1",
    )


def _seed_task_and_intent(
    conn: sqlite3.Connection, intents: SqliteIntentRepository, *, parameters: dict[str, object]
) -> None:
    conn.execute(
        "INSERT INTO tasks (id, session_id, request_id, state, created_at, updated_at) "
        "VALUES ('task-1', 's', 'req-1', 'COMPLETED', ?, ?)",
        (NOW.isoformat(), NOW.isoformat()),
    )
    conn.commit()
    intents.save(
        Intent(
            id="i-1",
            request_id="req-1",
            type="task",
            goal="do the thing",
            parameters=parameters,
            confidence=1.0,
            source="text",
            created_at=NOW,
        )
    )


def test_task_completion_attributes_memory_to_the_requests_profile(
    conn: sqlite3.Connection, unit_of_work: SqliteUnitOfWork
) -> None:
    """Regression: profile attribution must survive intents no longer
    carrying profile params."""
    model = ScriptedModelProvider()
    model.queue_response(_memories("likes dark mode"))
    bus, broker, requests, intents = _build(conn, unit_of_work, model)
    requests.save(_request("req-1", profile_id="personal"))
    _seed_task_and_intent(conn, intents, parameters={})

    bus.publish(_complete_task_event("task-1"))

    assert [p.profile_id for p in broker.proposals] == ["personal"]
    assert broker.proposals[0].task_id == "task-1"


def test_legacy_intent_without_request_row_falls_back_to_intent_params(
    conn: sqlite3.Connection, unit_of_work: SqliteUnitOfWork
) -> None:
    model = ScriptedModelProvider()
    model.queue_response(_memories("legacy fact"))
    bus, broker, _, intents = _build(conn, unit_of_work, model)
    _seed_task_and_intent(conn, intents, parameters={"profile_id": "old-profile"})

    bus.publish(_complete_task_event("task-1"))

    assert [p.profile_id for p in broker.proposals] == ["old-profile"]