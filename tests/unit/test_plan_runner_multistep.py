from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from shea.app.supervisor import ExecutionSupervisor
from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import TaskState
from shea.contracts.models import Plan, PlanStep, Task
from shea.core.orchestrator import Orchestrator
from shea.decision.service import DecisionService
from shea.execution.plan_runner import STEP_COMPLETED, PlanRunner
from shea.execution.service import ExecutionService
from shea.persistence.sqlite.authorization_repository import SqliteAuthorizationRepository
from shea.persistence.sqlite.decision_repository import SqliteDecisionRepository
from shea.persistence.sqlite.plan_repository import SqlitePlanRepository
from shea.persistence.sqlite.tool_execution_repository import SqliteToolExecutionRepository
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.security.filesystem_policy import FilesystemPolicy
from shea.security.service import SecurityService
from shea.tools.builtin import BuiltinFilesystemProvider
from shea.tools.executor import ToolExecutor
from shea.tools.provider import load_tools
from shea.tools.registry import ToolRegistry
from shea.verification.service import VerificationService
from shea.verification.verifier import VerifierRegistry


@pytest.fixture
def filesystem_policy(tmp_path: Path) -> FilesystemPolicy:
    """Override conftest default so SecurityGate + builtins share one root."""
    root = tmp_path / "workspace"
    root.mkdir()
    return FilesystemPolicy(allowed_roots=frozenset({str(root)}))


@pytest.fixture
def workspace(filesystem_policy: FilesystemPolicy) -> Path:
    return Path(next(iter(filesystem_policy.allowed_roots)))


def test_two_step_write_then_read(
    ready_task: Task,
    execution_supervisor: ExecutionSupervisor,
    orchestrator: Orchestrator,
    decision_service: DecisionService,
    verification_service: VerificationService,
    security_service: SecurityService,
    plan_repository: SqlitePlanRepository,
    authorization_repository: SqliteAuthorizationRepository,
    decision_repository: SqliteDecisionRepository,
    tool_execution_repository: SqliteToolExecutionRepository,
    verifier_registry: VerifierRegistry,
    audit_recorder: AuditRecorder,
    unit_of_work: SqliteUnitOfWork,
    id_generator: IdGenerator,
    clock: Clock,
    workspace: Path,
    filesystem_policy: FilesystemPolicy,
    conn: sqlite3.Connection,
) -> None:
    target = workspace / "note.txt"

    # Fresh registry: conftest's tool_registry already stubs filesystem.read
    registry = ToolRegistry()
    load_tools(
        registry,
        [BuiltinFilesystemProvider(filesystem_policy)],
        verifier_registry=verifier_registry,
    )
    executor = ToolExecutor(registry, allow_unsafe_execution=True)

    # Same wiring as conftest / e2e — audit + unit_of_work required
    execution_service = ExecutionService(
        tool_executor=executor,
        execution_supervisor=execution_supervisor,
        orchestrator=orchestrator,
        authorization_repository=authorization_repository,
        decision_repository=decision_repository,
        plan_repository=plan_repository,
        tool_execution_repository=tool_execution_repository,
        audit=audit_recorder,
        id_generator=id_generator,
        security_service=security_service,
        unit_of_work=unit_of_work,
        clock=clock,
    )

    plan_id = id_generator.new_id()
    plan = Plan(
        id=plan_id,
        task_id=ready_task.id,
        objective="write then read a note",
        steps=[
            PlanStep(
                id=id_generator.new_id(),
                plan_id=plan_id,
                order=1,
                description="write",
                tool="filesystem.write",
                arguments={"path": str(target), "content": "hello multi-step"},
                state="PENDING",
            ),
            PlanStep(
                id=id_generator.new_id(),
                plan_id=plan_id,
                order=2,
                description="read",
                tool="filesystem.read",
                arguments={"path": str(target)},
                state="PENDING",
            ),
        ],
    )
    with unit_of_work:
        plan_repository.save(plan)
        orchestrator.attach_plan(ready_task.id, plan_id)

    task = orchestrator.get_task(ready_task.id)
    assert task is not None
    assert task.state is TaskState.READY

    runner = PlanRunner(
        decision_service=decision_service,
        execution_service=execution_service,
        verification_service=verification_service,
        security_service=security_service,
        plan_repository=plan_repository,
        tool_registry=registry,
    )
    result = runner.run(task, explicit_user_ack=True)

    assert result.task.state is TaskState.COMPLETED
    assert result.stopped_early is False
    assert result.completed_steps == 2
    assert len(result.step_results) == 2
    assert target.read_text(encoding="utf-8") == "hello multi-step"

    reloaded = plan_repository.get_by_task(ready_task.id)
    assert reloaded is not None
    assert all(s.state == STEP_COMPLETED for s in reloaded.steps)

    # Audit trail was written under the shared unit of work
    rows = conn.execute(
        "SELECT * FROM audit_events WHERE task_id = ?",
        (ready_task.id,),
    ).fetchall()
    assert len(rows) > 0