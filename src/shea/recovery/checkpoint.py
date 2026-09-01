from __future__ import annotations

from shea.contracts.models import RecoveryCheckpoint
from shea.ports.repositories import TaskRepository


class RecoveryCheckpointService:
    """Maintains the durable point from which a task can safely resume."""

    def __init__(self, task_repository: TaskRepository) -> None:
        self._tasks = task_repository

    def checkpoint(
        self,
        checkpoint: RecoveryCheckpoint,
    ) -> None:
        task = self._tasks.get(checkpoint.task_id)

        if task is None:
            raise ValueError(
                f"Cannot checkpoint unknown task {checkpoint.task_id!r}"
            )

        # Task itself remains the authoritative lifecycle record.
        # Additional checkpoint persistence should be added once the
        # multi-step Plan executor exists.
        task.updated_at = task.updated_at
        self._tasks.save(task)