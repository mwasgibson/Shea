from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from shea.contracts.models import (
    Authorization,
    Plan,
    PlanStep,
)
from shea.core.orchestrator import Orchestrator
from shea.persistence.sqlite.authorization_repository import SqliteAuthorizationRepository
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from shea.security.binding import (
    compute_arguments_hash,
    compute_plan_hash,
    compute_step_hash,
    generate_nonce,
)
from tests.conftest import FrozenClock


def test_compute_hash_functions():
    """Test that hash functions produce consistent results."""
    plan = Plan(
        id="plan-1",
        task_id="task-1",
        objective="test",
        steps=[
            PlanStep(
                id="step-1",
                plan_id="plan-1",
                order=1,
                description="Test step",
                tool="test_tool",
                arguments={"arg1": "value1"},
            )
        ],
    )

    step = plan.steps[0]
    arguments = {"arg1": "value1"}

    plan_hash = compute_plan_hash(plan)
    step_hash = compute_step_hash(step)
    args_hash = compute_arguments_hash(arguments)

    assert len(plan_hash) == 64  # SHA-256 hex
    assert len(step_hash) == 64
    assert len(args_hash) == 64

    # Same content should produce same hash
    assert compute_plan_hash(plan) == plan_hash
    assert compute_step_hash(step) == step_hash
    assert compute_arguments_hash(arguments) == args_hash

def test_nonce_generation():
    """Test that nonces are unique and properly formatted."""
    nonce1 = generate_nonce()
    nonce2 = generate_nonce()

    assert len(nonce1) == 32  # 16 bytes = 32 hex chars
    assert nonce1 != nonce2

def test_authorization_with_binding_fields(
    conn: sqlite3.Connection, clock: FrozenClock, orchestrator: Orchestrator
    ):
    """Test that authorization can be saved and loaded with binding fields."""
    uow = SqliteUnitOfWork(conn)
    repo = SqliteAuthorizationRepository(conn, unit_of_work=uow)
    task = orchestrator.create_task(session_id="session-1", request_id="req-1")

    auth = Authorization(
        id="auth-1",
        task_id=task.id,
        granted=True,
        granted_by="user1",
        explicit=True,
        plan_hash="a" * 64,
        step_hash="b" * 64,
        arguments_hash="c" * 64,
        expires_at=clock.now() + timedelta(hours=1),
        used_at=None,
        nonce="nonce-123",
    )

    repo.save(auth)
    loaded = repo.list_by_task(task.id)

    assert len(loaded) == 1
    assert loaded[0].id == auth.id
    assert loaded[0].plan_hash == auth.plan_hash
    assert loaded[0].step_hash == auth.step_hash
    assert loaded[0].arguments_hash == auth.arguments_hash
    assert loaded[0].nonce == auth.nonce

def test_binding_mismatch_detection():
    """Test that binding mismatches are detected."""
    plan = Plan(
        id="plan-1",
        task_id="task-1",
        objective="test",
        steps=[
            PlanStep(
                id="step-1",
                plan_id="plan-1",
                order=1,
                description="Test step",
                tool="test_tool",
                arguments={"arg1": "value1"},
            )
        ],
    )

    # Original hashes
    plan_hash = compute_plan_hash(plan)
    step_hash = compute_step_hash(plan.steps[0])
    args_hash = compute_arguments_hash({"arg1": "value1"})

    # Modified plan
    modified_plan = Plan(
        id="plan-1",
        task_id="task-1",
        objective="test modified",
        steps=plan.steps,
    )
    modified_plan_hash = compute_plan_hash(modified_plan)

    assert plan_hash != modified_plan_hash
    assert step_hash

    # Modified arguments
    modified_args_hash = compute_arguments_hash({"arg1": "value2"})
    assert args_hash != modified_args_hash

def test_authorization_expiry_check(clock: FrozenClock):
    """Test that expired authorizations are detected."""
    now = clock.now()
    expired_at = now - timedelta(hours=1)

    auth = Authorization(
        id="auth-1",
        task_id="task-1",
        granted=True,
        granted_by="user1",
        expires_at=expired_at,
    )

    assert auth.expires_at is not None
    assert auth.expires_at < now

def test_authorization_used_check():
    """Test that used authorizations are detected."""
    auth = Authorization(
        id="auth-1",
        task_id="task-1",
        granted=True,
        granted_by="user1",
        used_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert auth.used_at is not None