from __future__ import annotations

import sqlite3

import pytest

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import TaskState
from shea.contracts.models import Task, ToolRequest, ToolResponse
from shea.core.orchestrator import Orchestrator
from shea.execution.service import (
    ExecutionService,
    MissingDecisionError,
    TaskNotRunningError,
)
from shea.persistence.sqlite.decision_repository import SqliteDecisionRepository
from shea.persistence.sqlite.tool_execution_repository import SqliteToolExecutionRepository
from shea.ports.id_generator import IdGenerator
from shea.tools.executor import ToolExecutor, UnknownOutcomeError
from shea.tools.registry import ToolDeclaration, ToolRegistry


def register_echo(registry: ToolRegistry, capabilities: frozenset[str] = frozenset()) -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True, data=request.arguments)

    registry.register(ToolDeclaration(name="echo", capabilities=capabilities), handler)


def register_failing(registry: ToolRegistry) -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=False, error="deliberate failure")

    registry.register(ToolDeclaration(name="fail", capabilities=frozenset()), handler)


def register_unknown(registry: ToolRegistry) -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        raise UnknownOutcomeError("dropped connection")

    registry.register(ToolDeclaration(name="flaky", capabilities=frozenset()), handler)


def test_successful_execution_advances_task_to_verifying(
    execution_service: ExecutionService, running_task: Task, tool_registry: ToolRegistry
) -> None:
    register_echo(tool_registry, capabilities=frozenset({"weather.lookup"}))
    request = ToolRequest(request_id="req-1", tool="echo", action="lookup")

    result = execution_service.execute(running_task, request)

    assert result.task.state == TaskState.VERIFYING
    assert result.response.success is True


def test_failing_execution_advances_task_to_failed(
    execution_service: ExecutionService, running_task: Task, tool_registry: ToolRegistry
) -> None:
    register_failing(tool_registry)
    request = ToolRequest(request_id="req-1", tool="fail", action="do_thing")

    result = execution_service.execute(running_task, request)

    assert result.task.state == TaskState.FAILED
    assert result.response.success is False


def test_unknown_outcome_advances_task_to_blocked_not_failed(
    execution_service: ExecutionService, running_task: Task, tool_registry: ToolRegistry
) -> None:
    """Research doc Section 12.13: UNKNOWN must never collapse into
    FAILED. It routes to BLOCKED — pending investigation — not straight
    to the failure path, and definitely not straight to retry.
    """
    register_unknown(tool_registry)
    request = ToolRequest(request_id="req-1", tool="flaky", action="do_thing")

    result = execution_service.execute(running_task, request)

    assert result.task.state == TaskState.BLOCKED
    assert result.task.state != TaskState.FAILED


def test_capability_not_authorized_advances_task_to_failed_without_running_tool(
    execution_service: ExecutionService, running_task: Task, tool_registry: ToolRegistry
) -> None:
    """running_task was authorized only for {"weather.lookup"}. Registering
    a tool that declares a capability outside that set must block
    execution entirely — the handler must not fire — and the task ends
    up FAILED, not silently stuck.
    """
    calls: list[ToolRequest] = []

    def handler(request: ToolRequest) -> ToolResponse:
        calls.append(request)
        return ToolResponse(success=True)

    tool_registry.register(
        ToolDeclaration(name="dangerous", capabilities=frozenset({"credential.access"})),
        handler,
    )
    request = ToolRequest(request_id="req-1", tool="dangerous", action="do_thing")

    result = execution_service.execute(running_task, request)

    assert len(calls) == 0
    assert result.task.state == TaskState.FAILED
    assert result.response.success is False


def test_execution_on_non_running_task_raises(
    execution_service: ExecutionService, ready_task: Task, tool_registry: ToolRegistry
) -> None:
    register_echo(tool_registry)
    request = ToolRequest(request_id="req-1", tool="echo", action="do_thing")

    with pytest.raises(TaskNotRunningError):
        execution_service.execute(ready_task, request)


def test_execution_without_decision_raises(
    tool_executor: ToolExecutor,
    orchestrator: Orchestrator,
    decision_repository: SqliteDecisionRepository,
    tool_execution_repository: SqliteToolExecutionRepository,
    audit_recorder: AuditRecorder,
    id_generator: IdGenerator,
    tool_registry: ToolRegistry,
) -> None:
    """Structurally, only DecisionService can move a task to RUNNING, and
    it always persists a Decision first — but ExecutionService checks
    this defensively rather than assuming the invariant always held.
    """
    task = orchestrator.create_task(session_id="session-1", request_id="req-1")
    orchestrator.advance(task.id, "start_planning")
    orchestrator.advance(task.id, "plan_ready")
    # Deliberately skip DecisionService and force RUNNING directly, so no
    # Decision row exists for this task.
    running = orchestrator.advance(task.id, "authorize_and_run")

    service = ExecutionService(
        tool_executor=tool_executor,
        orchestrator=orchestrator,
        decision_repository=decision_repository,
        tool_execution_repository=tool_execution_repository,
        audit=audit_recorder,
        id_generator=id_generator,
    )
    register_echo(tool_registry)
    request = ToolRequest(request_id="req-1", tool="echo", action="do_thing")

    with pytest.raises(MissingDecisionError):
        service.execute(running, request)


def test_successful_execution_is_audited(
    execution_service: ExecutionService,
    running_task: Task,
    tool_registry: ToolRegistry,
    conn: sqlite3.Connection,
) -> None:
    register_echo(tool_registry, capabilities=frozenset({"weather.lookup"}))
    request = ToolRequest(request_id="req-1", tool="echo", action="lookup")

    execution_service.execute(running_task, request)

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE task_id = ? AND event_type = ?",
        (running_task.id, "execution.success"),
    ).fetchall()
    assert len(rows) == 1


def test_capability_denial_is_audited(
    execution_service: ExecutionService,
    running_task: Task,
    tool_registry: ToolRegistry,
    conn: sqlite3.Connection,
) -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True)

    tool_registry.register(
        ToolDeclaration(name="dangerous", capabilities=frozenset({"credential.access"})),
        handler,
    )
    request = ToolRequest(request_id="req-1", tool="dangerous", action="do_thing")

    execution_service.execute(running_task, request)

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE task_id = ? AND event_type = ?",
        (running_task.id, "execution.capability_denied"),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "denied"