from datetime import UTC, datetime

from shea.contracts.enums import TaskState
from shea.contracts.models import Task
from shea.persistence.sqlite.task_repository import SqliteTaskRepository
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork


def test_list_transient_tasks(conn):
    uow = SqliteUnitOfWork(conn)
    repo = SqliteTaskRepository(conn, unit_of_work=uow)

    # Insert one task in each state
    now = datetime.now(UTC)
    for state in TaskState:
        task = Task(
            id=f"task_{state.value}",
            session_id="session_1",
            request_id="req_1",
            state=state,
            plan_id=None,
            created_at=now,
            updated_at=now,
        )
        repo.save(task)

    transient = repo.list_transient_tasks()
    transient_states = {t.state for t in transient}

    assert TaskState.CREATED in transient_states
    assert TaskState.PLANNING in transient_states
    assert TaskState.READY in transient_states
    assert TaskState.RUNNING in transient_states
    assert TaskState.VERIFYING in transient_states
    assert TaskState.RECOVERING in transient_states

    assert TaskState.COMPLETED not in transient_states
    assert TaskState.CANCELLED not in transient_states
    assert TaskState.SECURITY_HALT not in transient_states
    assert TaskState.FAILED not in transient_states
    assert TaskState.BLOCKED not in transient_states


def test_reconcile_stranded_tasks_forces_to_stable_states(recovery_service, orchestrator):
    # Re-wire to orchestrator if needed
    recovery_service._orchestrator = orchestrator

    now = datetime.now(UTC)
    # Create stranded tasks via repository
    transient_states = [
        TaskState.CREATED, TaskState.PLANNING, TaskState.READY, 
        TaskState.RUNNING, TaskState.VERIFYING, TaskState.RECOVERING
    ]
    for state in transient_states:
        task = Task(
            id=f"strand_{state.value}",
            session_id="session_stranded",
            request_id="req_stranded",
            state=state,
            plan_id=None,
            created_at=now,
            updated_at=now,
        )
        orchestrator._tasks.save(task)
    
    # Run reconciliation
    reconciled = recovery_service.reconcile_stranded_tasks()

    assert len(reconciled) == len(transient_states)
    
    # Verify the results in Orchestrator
    for state in transient_states:
        task = orchestrator.get_task(f"strand_{state.value}")
        if state in (TaskState.CREATED, TaskState.PLANNING, TaskState.READY):
            assert task.state == TaskState.CANCELLED
        elif state == TaskState.RUNNING:
            assert task.state == TaskState.BLOCKED
        elif state in (TaskState.VERIFYING, TaskState.RECOVERING):
            assert task.state == TaskState.FAILED

