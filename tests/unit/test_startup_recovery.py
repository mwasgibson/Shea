from __future__ import annotations

from shea.app.contracts import ExecutionReceipt
from shea.app.enums import ReceiptState
from shea.contracts.enums import TaskState
from shea.core.orchestrator import Orchestrator
from shea.persistence.sqlite.app_receipt_repository import SqliteAppReceiptRepository
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.recovery.startup import StartupRecoveryService


def test_startup_reconciles_interrupted_receipt_into_failed_task(
    ready_task,
    task_repository,
    orchestrator: Orchestrator,
    execution_supervisor,
    conn,
    unit_of_work,
    clock: Clock,
    id_generator: IdGenerator,
) -> None:
    task = orchestrator.advance(ready_task.id, "authorize_and_run")
    receipt_repository = SqliteAppReceiptRepository(conn, unit_of_work=unit_of_work)
    receipt_repository.save(
        ExecutionReceipt(
            id=id_generator.new_id(),
            contract_id=id_generator.new_id(),
            authorization_id="authorization-1",
            capability="filesystem.write",
            operation="tool.filesystem.write.write",
            target="filesystem.write",
            state=ReceiptState.ATTEMPTING,
            created_at=clock.now(),
            metadata={"task_id": task.id},
        )
    )

    service = StartupRecoveryService(
        task_repository=task_repository,
        orchestrator=orchestrator,
        app_receipt_repository=receipt_repository,
        app_supervisor=execution_supervisor,
    )

    assert service.reconcile_app_receipts() == [task.id]
    assert orchestrator.get_task(task.id).state is TaskState.FAILED
