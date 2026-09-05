from __future__ import annotations

import sqlite3

import pytest

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import TaskState
from shea.contracts.models import Task
from shea.core.orchestrator import Orchestrator
from shea.decision.exceptions import AuthorizationRequiredError, PolicyDeniedError
from shea.decision.policy import PolicyEngine
from shea.decision.risk import RiskEngine
from shea.decision.service import DecisionService
from shea.persistence.sqlite.authorization_repository import SqliteAuthorizationRepository
from shea.persistence.sqlite.decision_repository import SqliteDecisionRepository
from shea.persistence.sqlite.risk_repository import SqliteRiskAssessmentRepository
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator


def test_safe_action_auto_authorizes_and_advances_task(
    decision_service: DecisionService, ready_task: Task
) -> None:
    outcome = decision_service.evaluate_and_authorize(
        ready_task, capabilities=frozenset({"weather.lookup"})
    )

    assert outcome.decision.requires_authorization is False
    assert outcome.authorization.granted is True
    assert outcome.authorization.explicit is False
    assert outcome.authorization.granted_by == "system"
    assert outcome.task.state == TaskState.RUNNING


def test_medium_risk_proceeds_with_implicit_authorization_without_ack(
    decision_service: DecisionService, ready_task: Task
) -> None:
    """MEDIUM tier ("optional acknowledgement") must not block execution
    even when no explicit_user_ack is supplied.
    """
    outcome = decision_service.evaluate_and_authorize(
        ready_task,
        capabilities=frozenset({"process.execute", "network.connect"}),
        explicit_user_ack=False,
    )

    assert outcome.decision.risk.value == "MEDIUM"
    assert outcome.authorization.granted is True
    assert outcome.authorization.explicit is False
    assert outcome.task.state == TaskState.RUNNING


def test_high_risk_without_ack_blocks_and_does_not_advance_task(
    decision_service: DecisionService, ready_task: Task, orchestrator: Orchestrator
) -> None:
    with pytest.raises(AuthorizationRequiredError) as exc_info:
        decision_service.evaluate_and_authorize(
            ready_task,
            capabilities=frozenset({"process.execute", "network.connect"}),
            reversible=False,  # 3 factors -> HIGH
            explicit_user_ack=False,
        )

    assert exc_info.value.decision.risk.value == "HIGH"
    # Task must remain exactly where it was — no partial advancement.
    unchanged = orchestrator.get_task(ready_task.id)
    assert unchanged.state == TaskState.READY


def test_high_risk_with_explicit_ack_proceeds_and_advances_task(
    decision_service: DecisionService, ready_task: Task
) -> None:
    """WARNING != DENIAL (Appendix B): a HIGH-risk action is not vetoed —
    an explicit user acknowledgement unblocks it.
    """
    outcome = decision_service.evaluate_and_authorize(
        ready_task,
        capabilities=frozenset({"process.execute", "network.connect"}),
        reversible=False,
        explicit_user_ack=True,
        acting_user="alice",
    )

    assert outcome.decision.risk.value == "HIGH"
    assert outcome.authorization.granted is True
    assert outcome.authorization.explicit is True
    assert outcome.authorization.granted_by == "alice"
    assert outcome.task.state == TaskState.RUNNING


@pytest.fixture
def denying_decision_service(
    orchestrator: Orchestrator,
    decision_repository: SqliteDecisionRepository,
    risk_assessment_repository: SqliteRiskAssessmentRepository,
    authorization_repository: SqliteAuthorizationRepository,
    unit_of_work: SqliteUnitOfWork,
    audit_recorder: AuditRecorder,
    clock: Clock,
    id_generator: IdGenerator,
) -> DecisionService:
    """Same wiring as the `decision_service` fixture, but with a policy
    engine that explicitly denies `credential.access` — used to test the
    non-negotiable DENIED tier without touching the default fixture that
    every other test relies on.
    """
    return DecisionService(
        policy_engine=PolicyEngine(deny_capabilities=frozenset({"credential.access"})),
        risk_engine=RiskEngine(),
        orchestrator=orchestrator,
        decision_repository=decision_repository,
        risk_repository=risk_assessment_repository,
        authorization_repository=authorization_repository,
        audit=audit_recorder,
        clock=clock,
        id_generator=id_generator,
        unit_of_work=unit_of_work,
    )


def test_policy_denied_capability_blocks_even_with_explicit_ack(
    denying_decision_service: DecisionService,
    ready_task: Task,
    orchestrator: Orchestrator,
) -> None:
    """The core non-negotiable invariant: PolicyVerdict.DENIED cannot be
    bypassed by explicit_user_ack=True. There is no override for this
    tier, unlike risk-based authorization requirements.
    """
    with pytest.raises(PolicyDeniedError):
        denying_decision_service.evaluate_and_authorize(
            ready_task,
            capabilities=frozenset({"credential.access"}),
            explicit_user_ack=True,  # deliberately try to override — must not work
        )

    unchanged = orchestrator.get_task(ready_task.id)
    assert unchanged.state == TaskState.READY


def test_policy_denial_is_audited(
    denying_decision_service: DecisionService,
    ready_task: Task,
    conn: sqlite3.Connection,
) -> None:
    with pytest.raises(PolicyDeniedError):
        denying_decision_service.evaluate_and_authorize(
            ready_task, capabilities=frozenset({"credential.access"})
        )

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE task_id = ? AND event_type = ?",
        (ready_task.id, "decision.policy_denied"),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "denied"


def test_awaiting_authorization_is_audited(
    decision_service: DecisionService, ready_task: Task, conn: sqlite3.Connection
) -> None:
    with pytest.raises(AuthorizationRequiredError):
        decision_service.evaluate_and_authorize(
            ready_task,
            capabilities=frozenset({"process.execute", "network.connect"}),
            reversible=False,
            explicit_user_ack=False,
        )

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE task_id = ? AND event_type = ?",
        (ready_task.id, "decision.authorization.awaiting"),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "blocked"


def test_explicit_authorization_is_persisted_and_retrievable(
    decision_service: DecisionService,
    ready_task: Task,
    authorization_repository: SqliteAuthorizationRepository,
) -> None:
    decision_service.evaluate_and_authorize(
        ready_task,
        capabilities=frozenset({"process.execute", "network.connect"}),
        reversible=False,
        explicit_user_ack=True,
        acting_user="bob",
    )

    records = authorization_repository.list_by_task(ready_task.id)
    assert len(records) == 1
    assert records[0].granted_by == "bob"
    assert records[0].explicit is True


def test_decision_and_risk_assessment_are_persisted(
    decision_service: DecisionService,
    ready_task: Task,
    decision_repository: SqliteDecisionRepository,
    risk_assessment_repository: SqliteRiskAssessmentRepository,
) -> None:
    decision_service.evaluate_and_authorize(
        ready_task,
        capabilities=frozenset({"process.execute", "network.connect"}),
        reversible=False,
        explicit_user_ack=True,
    )

    stored_decision = decision_repository.get_by_task(ready_task.id)
    stored_risk = risk_assessment_repository.get_by_task(ready_task.id)

    assert stored_decision is not None
    assert stored_decision.risk.value == "HIGH"
    assert stored_decision.requires_explicit_acknowledgement is True

    assert stored_risk is not None
    assert stored_risk.level.value == "HIGH"
    assert len(stored_risk.factors) == 3