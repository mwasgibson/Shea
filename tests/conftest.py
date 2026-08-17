from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shea.audit.recorder import AuditRecorder
from shea.config.resolver import ConfigResolver
from shea.contracts.models import Task
from shea.core.orchestrator import Orchestrator
from shea.decision.policy import PolicyEngine
from shea.decision.risk import RiskEngine
from shea.decision.service import DecisionService
from shea.persistence.sqlite.audit_sink import SqliteAuditSink
from shea.persistence.sqlite.authorization_repository import SqliteAuthorizationRepository
from shea.persistence.sqlite.connection import open_connection
from shea.persistence.sqlite.decision_repository import SqliteDecisionRepository
from shea.persistence.sqlite.migrator import run_migrations
from shea.persistence.sqlite.plan_repository import SqlitePlanRepository
from shea.persistence.sqlite.risk_repository import SqliteRiskAssessmentRepository
from shea.persistence.sqlite.task_repository import SqliteTaskRepository
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator


class FrozenClock(Clock):
    """Advances by one second on every call, so successive events get
    strictly increasing timestamps without relying on wall-clock time —
    keeps ordering assertions deterministic.
    """

    def __init__(self, start: datetime | None = None) -> None:
        self._current = start or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        value = self._current
        self._current = self._current + timedelta(seconds=1)
        return value


class SequentialIdGenerator(IdGenerator):
    """Predictable ids (id-1, id-2, ...) so tests can assert on them
    directly instead of matching a UUID pattern.
    """

    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._prefix}-{self._counter}"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "shea_test.db"


@pytest.fixture
def conn(db_path: Path) -> sqlite3.Connection:
    connection = open_connection(db_path)
    run_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def id_generator() -> SequentialIdGenerator:
    return SequentialIdGenerator()


@pytest.fixture
def task_repository(conn: sqlite3.Connection) -> SqliteTaskRepository:
    return SqliteTaskRepository(conn)


@pytest.fixture
def plan_repository(conn: sqlite3.Connection) -> SqlitePlanRepository:
    return SqlitePlanRepository(conn)


@pytest.fixture
def audit_sink(conn: sqlite3.Connection) -> SqliteAuditSink:
    return SqliteAuditSink(conn)


@pytest.fixture
def audit_recorder(
    audit_sink: SqliteAuditSink, clock: FrozenClock, id_generator: SequentialIdGenerator
) -> AuditRecorder:
    return AuditRecorder(sink=audit_sink, clock=clock, id_generator=id_generator)


@pytest.fixture
def orchestrator(
    task_repository: SqliteTaskRepository,
    audit_recorder: AuditRecorder,
    clock: FrozenClock,
    id_generator: SequentialIdGenerator,
) -> Orchestrator:
    return Orchestrator(
        task_repository=task_repository,
        audit=audit_recorder,
        clock=clock,
        id_generator=id_generator,
    )


@pytest.fixture
def config_resolver() -> ConfigResolver:
    return ConfigResolver()


@pytest.fixture
def risk_assessment_repository(conn: sqlite3.Connection) -> SqliteRiskAssessmentRepository:
    return SqliteRiskAssessmentRepository(conn)


@pytest.fixture
def decision_repository(conn: sqlite3.Connection) -> SqliteDecisionRepository:
    return SqliteDecisionRepository(conn)


@pytest.fixture
def authorization_repository(conn: sqlite3.Connection) -> SqliteAuthorizationRepository:
    return SqliteAuthorizationRepository(conn)


@pytest.fixture
def policy_engine() -> PolicyEngine:
    return PolicyEngine()


@pytest.fixture
def risk_engine() -> RiskEngine:
    return RiskEngine()


@pytest.fixture
def decision_service(
    policy_engine: PolicyEngine,
    risk_engine: RiskEngine,
    orchestrator: Orchestrator,
    decision_repository: SqliteDecisionRepository,
    risk_assessment_repository: SqliteRiskAssessmentRepository,
    authorization_repository: SqliteAuthorizationRepository,
    audit_recorder: AuditRecorder,
    clock: FrozenClock,
    id_generator: SequentialIdGenerator,
) -> DecisionService:
    return DecisionService(
        policy_engine=policy_engine,
        risk_engine=risk_engine,
        orchestrator=orchestrator,
        decision_repository=decision_repository,
        risk_repository=risk_assessment_repository,
        authorization_repository=authorization_repository,
        audit=audit_recorder,
        clock=clock,
        id_generator=id_generator,
    )


@pytest.fixture
def ready_task(orchestrator: Orchestrator) -> Task:
    """A task already advanced through CREATED -> PLANNING -> READY, i.e.
    exactly the state DecisionService expects to receive one in (planning
    happens upstream of Decision in the pipeline; Phase 2 doesn't build
    the Planning subsystem, so tests drive the state machine directly).
    """
    task = orchestrator.create_task(session_id="session-1", request_id="req-1")
    orchestrator.advance(task.id, "start_planning")
    return orchestrator.advance(task.id, "plan_ready")
