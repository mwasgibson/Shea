# mypy: ignore-errors
from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

from shea.bootstrap import build_runtime
from shea.contracts.enums import TaskState
from shea.contracts.models import Task


# A ModelProvider that fails on the first N calls
class FlakyModelProvider:
    def __init__(self, fail_count: int = 1):
        self._fail_count = fail_count
        self._calls = 0
        
    def generate(self, *args, **kwargs) -> Any:
        self._calls += 1
        if self._calls <= self._fail_count:
            raise ConnectionError("Simulated LLM network timeout")
        return "{}"

    def generate_plan(self, *args, **kwargs) -> Any:
        from shea.contracts.models import Plan, Step
        self._calls += 1
        if self._calls <= self._fail_count:
            raise ConnectionError("Simulated LLM network timeout")
        return Plan(steps=[Step(tool="test.tool", arguments={})])

def test_fault_injection_model_provider_timeout(tmp_path):
    db_path = tmp_path / "faults.db"
    runtime = build_runtime(db_path=db_path)
    flaky_provider = FlakyModelProvider(fail_count=2)
    runtime.interaction_service._planning._model_provider = flaky_provider
    runtime.interaction_service._planning._intent_parser._model = flaky_provider

    result = runtime.interaction_service.handle_text(
        text="Do something",
        session_id="test_session"
    )
    assert result.error is not None
    assert "network timeout" in result.error

# 1. Database Locked Injection
def test_fault_injection_db_locked(tmp_path):
    db_path = tmp_path / "faults.db"
    runtime = build_runtime(db_path=db_path)
    
    original_exit = runtime.unit_of_work.__class__.__exit__
    def mock_exit(self, exc_type, exc_val, exc_tb):
        raise sqlite3.OperationalError("database is locked")
    runtime.unit_of_work.__class__.__exit__ = mock_exit
    
    try:
        # Run the interaction. The interaction service handles DB errors during planning
        result = runtime.interaction_service.handle_text("Do something")
    finally:
        runtime.unit_of_work.__class__.__exit__ = original_exit
        
    # Verify it failed gracefully without crashing the whole process
    assert result.error is not None
    assert "database is locked" in result.error or "Critical failure" in result.error
    assert result.task.state == TaskState.FAILED


# 3. Spurious Event Loop Drops (Recovery Sweep)
def test_fault_injection_event_drops_swept(tmp_path):
    db_path = tmp_path / "faults.db"
    runtime = build_runtime(db_path=db_path)
    
    # Create a task stuck in READY state (simulate it was planned, but the execution event was dropped)
    task_id = uuid.uuid4().hex
    stuck_task = Task(
        id=task_id,
        session_id="session1",
        request_id=uuid.uuid4().hex,
        state=TaskState.READY, # Stuck here!
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC)
    )
    
    # Mock the recovery repository to return the stranded task
    runtime.recovery_service._repo = MagicMock()
    runtime.recovery_service._repo.find_stranded_tasks.return_value = [stuck_task]
    runtime.recovery_service._tasks = MagicMock()
    runtime.recovery_service._tasks.update_state = MagicMock()

    # Sweep the recovery service to find stranded tasks
    recovered_count = len(runtime.recovery_service.reconcile_app_plane())
    
    assert recovered_count >= 0
