from __future__ import annotations

from shea.app.enums import AppOutcome
from shea.app.ports import ReceiptRepository
from shea.app.supervisor import ExecutionSupervisor
from shea.contracts.enums import TaskState
from shea.core.orchestrator import Orchestrator
from shea.ports.repositories import TaskRepository


class StartupRecoveryService:
    """Finds tasks left in recoverable states after a process crash."""

    def __init__(
        self,
        *,
        task_repository: TaskRepository,
        orchestrator: Orchestrator,
        app_receipt_repository: ReceiptRepository | None = None,
        app_supervisor: ExecutionSupervisor | None = None,
    ) -> None:
        self._tasks = task_repository
        self._orchestrator = orchestrator
        self._app_receipts = app_receipt_repository
        self._app_supervisor = app_supervisor

    def recover(self, task_ids: list[str]) -> list[str]:
        recovered: list[str] = []

        for task_id in task_ids:
            task = self._tasks.get(task_id)

            if task is None:
                continue

            if task.state is TaskState.RECOVERING:
                recovered.append(task_id)

            elif task.state is TaskState.VERIFYING:
                recovered.append(task_id)

            elif task.state is TaskState.RUNNING:
                recovered.append(task_id)

        return recovered

    def reconcile_app_receipts(self) -> list[str]:
        """Finalize interrupted app executions and advance their core tasks."""
        if self._app_receipts is None or self._app_supervisor is None:
            return []

        reconciled: list[str] = []
        for receipt in self._app_receipts.list_unfinalized():
            task_id = receipt.metadata.get("task_id")
            if not isinstance(task_id, str):
                continue

            result = self._app_supervisor.reconcile_receipt(receipt.id)
            task = self._tasks.get(task_id)
            if task is None or task.state not in (TaskState.RUNNING, TaskState.VERIFYING):
                continue

            event = (
                "execution_unknown"
                if result.outcome is AppOutcome.UNKNOWN
                else "execution_failed"
            )
            self._orchestrator.advance(task_id, event)
            reconciled.append(task_id)

        return reconciled