from __future__ import annotations

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
    ) -> None:
        self._tasks = task_repository
        self._orchestrator = orchestrator

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