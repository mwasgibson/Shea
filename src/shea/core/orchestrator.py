from __future__ import annotations

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import TaskState
from shea.contracts.models import Task
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.repositories import TaskRepository
from shea.state_machine.transitions import IllegalTransitionError, next_state


class TaskNotFoundError(Exception):
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"No task found with id {task_id!r}")


class Orchestrator:
    """Coordinates task lifecycle — technical doc Component: Core Orchestrator.

    Phase 1 scope, deliberately: this class knows how to create a task and
    move it between states via the state machine, and it audits every
    attempt (successful or rejected). It does NOT know how to plan,
    assess risk, call a model, or execute a tool — those subsystems will
    be given their own ports and will call into this orchestrator, not the
    other way around, keeping `MODEL != AUTHORITY` (Appendix B) true by
    construction: nothing outside this class can move a Task's state.
    """

    def __init__(
        self,
        task_repository: TaskRepository,
        audit: AuditRecorder,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._tasks = task_repository
        self._audit = audit
        self._clock = clock
        self._ids = id_generator

    def create_task(self, *, session_id: str, request_id: str) -> Task:
        now = self._clock.now()
        task = Task(
            id=self._ids.new_id(),
            session_id=session_id,
            request_id=request_id,
            state=TaskState.CREATED,
            created_at=now,
            updated_at=now,
        )
        self._tasks.save(task)
        self._audit.record(
            actor="orchestrator",
            component="core.orchestrator",
            event_type="task.created",
            action="create_task",
            result="success",
            request_id=request_id,
            task_id=task.id,
            metadata={"session_id": session_id},
        )
        return task

    def get_task(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    def advance(self, task_id: str, event: str) -> Task:
        """Attempt to move `task_id` forward by `event`.

        Every call is audited, whether it succeeds or is rejected as
        illegal — a rejected transition is itself a security-relevant
        fact (something tried to move a task somewhere it wasn't allowed
        to go), not just an error to swallow.
        """
        task = self.get_task(task_id)

        try:
            new_state = next_state(task.state, event)
        except IllegalTransitionError as exc:
            self._audit.record(
                actor="orchestrator",
                component="core.orchestrator",
                event_type="task.transition.rejected",
                action=event,
                result="illegal_transition",
                request_id=task.request_id,
                task_id=task.id,
                metadata={"from_state": task.state.value},
            )
            raise exc

        from_state = task.state
        task.state = new_state
        task.updated_at = self._clock.now()
        self._tasks.save(task)

        self._audit.record(
            actor="orchestrator",
            component="core.orchestrator",
            event_type="task.transition",
            action=event,
            result="success",
            request_id=task.request_id,
            task_id=task.id,
            metadata={"from_state": from_state.value, "to_state": new_state.value},
        )
        return task