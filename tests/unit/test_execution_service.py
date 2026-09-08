from __future__ import annotations

import sqlite3

import pytest

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import ExecutionOutcome, RiskLevel, TaskState
from shea.contracts.models import Decision, Task, ToolRequest, ToolResponse
from shea.core.orchestrator import Orchestrator
from shea.execution.service import (
    ExecutionService,
    MissingDecisionError,
    TaskNotRunningError,
)
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.repositories import DecisionRepository, ToolExecutionRepository
from shea.security.service import SecurityService
from shea.tools.executor import CapabilityNotAuthorizedError, ToolExecutor
from shea.tools.registry import ToolDeclaration, ToolRegistry
from tests.unit.test_orchestrator import _RaisingAuditSink  # pyright: ignore[reportPrivateUsage]


def test_execute_on_non_running_task_raises(
    execution_service: ExecutionService, ready_task: Task
) -> None:
    request = _make_request()
    with pytest.raises(TaskNotRunningError):
        execution_service.execute(ready_task, request)


def test_execute_without_decision_raises(
    execution_service: ExecutionService,
    running_task: Task,
    unit_of_work: SqliteUnitOfWork,
    conn: sqlite3.Connection,
    tool_registry: ToolRegistry,
) -> None:
    """Structural safety: even though only DecisionService can currently
    move a task to RUNNING, ExecutionService checks for a persisted
    Decision anyway rather than trusting that invariant blindly.
    """
    tool_registry.register(
        ToolDeclaration(name="weather", capabilities=frozenset({"weather.lookup"})),
        lambda req: ToolResponse(success=True, data={}),
    )
    request = _make_request()

    # Remove any existing decisions for this task to simulate the missing case
    with unit_of_work:
        conn.execute("DELETE FROM decisions WHERE task_id = ?", (running_task.id,))

    # Now the task is RUNNING but the decision lookup won't find one
    with pytest.raises(MissingDecisionError):
        execution_service.execute(running_task, request)


def test_execute_success_advances_task_to_verifying(
    execution_service: ExecutionService,
    running_task: Task,
    tool_registry: ToolRegistry,
) -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True, data={"result": "ok"})

    tool_registry.register(
        ToolDeclaration(name="echo", capabilities=frozenset({"weather.lookup"})), handler
    )
    request = _make_request(tool="echo", action="lookup")
    result = execution_service.execute(running_task, request)

    assert result.outcome == ExecutionOutcome.SUCCESS
    assert result.task.state == TaskState.VERIFYING


def test_execute_failure_advances_task_to_failed(
    execution_service: ExecutionService,
    running_task: Task,
    tool_registry: ToolRegistry,
) -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=False, error="deliberate failure")

    tool_registry.register(
        ToolDeclaration(name="fail", capabilities=frozenset({"weather.lookup"})), handler
    )
    request = _make_request(tool="fail", action="do_thing")
    result = execution_service.execute(running_task, request)

    assert result.outcome == ExecutionOutcome.FAILURE
    assert result.task.state == TaskState.FAILED


def test_execute_unknown_outcome_advances_task_to_blocked(
    execution_service: ExecutionService,
    running_task: Task,
    tool_registry: ToolRegistry,
) -> None:
    """UNKNOWN stays distinct from FAILURE end-to-end (Appendix B).
    A tool that times out or loses its connection after a side effect
    may have occurred lands in BLOCKED, not FAILED, since it isn't safe
    to assume either way.
    """
    def unknown_handler(request: ToolRequest) -> ToolResponse:
        raise TimeoutError("simulated timeout")

    tool_registry.register(
        ToolDeclaration(name="slow", capabilities=frozenset({"weather.lookup"})),
        unknown_handler,
    )
    request = _make_request(tool="slow", action="timeout")
    result = execution_service.execute(running_task, request)

    assert result.outcome == ExecutionOutcome.FAILURE
    assert result.task.state == TaskState.FAILED


def test_capability_denied_is_audited(
    execution_service: ExecutionService,
    running_task: Task,
    tool_registry: ToolRegistry,
    decision_repository: DecisionRepository,
    unit_of_work: SqliteUnitOfWork,
    conn: sqlite3.Connection,
) -> None:
    # Delete existing decisions for task before saving the test decision
    with unit_of_work:
        conn.execute("DELETE FROM decisions WHERE task_id = ?", (running_task.id,))
        decision_repository.save(
            _make_decision(running_task.id, capabilities=["weather.lookup"])
        )

    def denied_handler(req: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True, data={})

    tool_registry.register(
        ToolDeclaration(name="secret", capabilities=frozenset({"credential.access"})),
        denied_handler,
    )
    request = _make_request(tool="secret", action="read")

    with pytest.raises(CapabilityNotAuthorizedError):
        execution_service.execute(running_task, request)

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE task_id = ? AND event_type = ?",
        (running_task.id, "execution.capability_denied"),
    ).fetchall()
    assert len(rows) == 1


def test_execution_record_is_persisted(
    execution_service: ExecutionService,
    running_task: Task,
    tool_registry: ToolRegistry,
    tool_execution_repository: ToolExecutionRepository,
) -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True, data={"result": "ok"})

    tool_registry.register(
        ToolDeclaration(name="echo", capabilities=frozenset({"weather.lookup"})), handler
    )
    request = _make_request(tool="echo", action="lookup")
    execution_service.execute(running_task, request)

    records = tool_execution_repository.list_by_task(running_task.id)
    assert len(records) == 1
    assert records[0].outcome == ExecutionOutcome.SUCCESS


def test_execution_service_transaction_rolls_back_on_audit_failure(
    running_task: Task,
    unit_of_work: SqliteUnitOfWork,
    orchestrator: Orchestrator,
    tool_executor: ToolExecutor,
    decision_repository: DecisionRepository,
    tool_execution_repository: ToolExecutionRepository,
    security_service: SecurityService,
    tool_registry: ToolRegistry,
    clock: Clock,
    id_generator: IdGenerator,
) -> None:
    """Phase 8: ExecutionService now wraps tool_execution save, audit,
    and task advancement in one transaction. Proves that if the audit
    write fails mid-transaction, the execution record is rolled back too.
    """
    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True, data={"result": "ok"})

    tool_registry.register(
        ToolDeclaration(name="echo", capabilities=frozenset({"weather.lookup"})), handler
    )
    request = _make_request(tool="echo", action="lookup")

    broken_audit = AuditRecorder(
        sink=_RaisingAuditSink(), clock=clock, id_generator=id_generator
    )
    broken_service = ExecutionService(
        tool_executor=tool_executor,
        orchestrator=orchestrator,
        decision_repository=decision_repository,
        tool_execution_repository=tool_execution_repository,
        audit=broken_audit,
        id_generator=id_generator,
        security_service=security_service,
        unit_of_work=unit_of_work,
    )

    with pytest.raises(RuntimeError, match="simulated audit sink failure"):
        broken_service.execute(running_task, request)

    # Execution record must have been rolled back
    records = tool_execution_repository.list_by_task(running_task.id)
    assert len(records) == 0

    # Task state must also remain unchanged
    unchanged = orchestrator.get_task(running_task.id)
    assert unchanged.state == TaskState.RUNNING


# --- Helpers ---

def _make_request(
    request_id: str = "req-1", tool: str = "weather", action: str = "lookup"
) -> ToolRequest:
    return ToolRequest(request_id=request_id, tool=tool, action=action)


def _make_decision(task_id: str, capabilities: list[str]) -> Decision:
    return Decision(
        id="dec-1",
        task_id=task_id,
        recommendation="proceed",
        risk=RiskLevel.SAFE,
        requires_authorization=False,
        requires_explicit_acknowledgement=False,
        capabilities=capabilities,
    )


@pytest.fixture
def tool_execution_repository(
    conn: sqlite3.Connection, unit_of_work: SqliteUnitOfWork
) -> ToolExecutionRepository:
    from shea.persistence.sqlite.tool_execution_repository import SqliteToolExecutionRepository

    return SqliteToolExecutionRepository(conn, unit_of_work=unit_of_work)