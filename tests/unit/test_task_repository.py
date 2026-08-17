from __future__ import annotations

from datetime import UTC, datetime

from shea.contracts.enums import TaskState
from shea.contracts.models import Task
from shea.persistence.sqlite.task_repository import SqliteTaskRepository


def make_task(**overrides: object) -> Task:
    defaults = dict(
        id="task-1",
        session_id="session-1",
        request_id="req-1",
        state=TaskState.CREATED,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        plan_id=None,
    )
    defaults.update(overrides)
    return Task(**defaults)  # type: ignore[arg-type]


def test_save_and_get_round_trip(task_repository: SqliteTaskRepository) -> None:
    task = make_task()
    task_repository.save(task)

    fetched = task_repository.get("task-1")

    assert fetched is not None
    assert fetched.id == task.id
    assert fetched.session_id == task.session_id
    assert fetched.request_id == task.request_id
    assert fetched.state == TaskState.CREATED
    assert fetched.created_at == task.created_at
    assert fetched.updated_at == task.updated_at
    assert fetched.plan_id is None


def test_get_missing_task_returns_none(task_repository: SqliteTaskRepository) -> None:
    assert task_repository.get("does-not-exist") is None


def test_save_upserts_existing_task(task_repository: SqliteTaskRepository) -> None:
    task = make_task()
    task_repository.save(task)

    task.state = TaskState.PLANNING
    task.plan_id = "plan-1"
    task_repository.save(task)

    fetched = task_repository.get("task-1")
    assert fetched is not None
    assert fetched.state == TaskState.PLANNING
    assert fetched.plan_id == "plan-1"


def test_list_by_session_filters_and_orders(
    task_repository: SqliteTaskRepository,
) -> None:
    t1 = make_task(
        id="task-1", session_id="session-a", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    t2 = make_task(
        id="task-2", session_id="session-a", created_at=datetime(2026, 1, 2, tzinfo=UTC)
    )
    t3 = make_task(
        id="task-3", session_id="session-b", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    for t in (t1, t2, t3):
        task_repository.save(t)

    results = task_repository.list_by_session("session-a")

    assert [t.id for t in results] == ["task-1", "task-2"]
