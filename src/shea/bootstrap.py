from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from shea.adapters.system import SystemClock, UuidIdGenerator
from shea.app.adapters.tool_executor import ToolExecutorAdapter
from shea.app.identity import IdentityResolver, IdentityRevalidator
from shea.app.interaction.service import InteractionService
from shea.app.recovery import ReconciliationResult
from shea.app.supervisor import ExecutionSupervisor
from shea.audit.recorder import AuditRecorder
from shea.bootstrap_demo import register_demo_intent
from shea.core.orchestrator import Orchestrator
from shea.decision.policy import PolicyEngine
from shea.decision.risk import RiskEngine
from shea.decision.service import DecisionService
from shea.execution.plan_runner import PlanRunner
from shea.execution.service import ExecutionService
from shea.model.factory import model_provider_from_env
from shea.persistence.sqlite.app_attempt_repository import SqliteAppAttemptRepository
from shea.persistence.sqlite.app_evidence_repository import SqliteAppEvidenceRepository
from shea.persistence.sqlite.app_idempotency_repository import SqliteAppIdempotencyRepository
from shea.persistence.sqlite.app_receipt_repository import SqliteAppReceiptRepository
from shea.persistence.sqlite.app_recovery_repository import SqliteAppRecoveryRepository
from shea.persistence.sqlite.app_verification_repository import SqliteAppVerificationRepository
from shea.persistence.sqlite.audit_sink import SqliteAuditSink
from shea.persistence.sqlite.authorization_repository import SqliteAuthorizationRepository
from shea.persistence.sqlite.connection import open_connection
from shea.persistence.sqlite.decision_repository import SqliteDecisionRepository
from shea.persistence.sqlite.intent_repository import SqliteIntentRepository
from shea.persistence.sqlite.migrator import run_migrations
from shea.persistence.sqlite.plan_repository import SqlitePlanRepository
from shea.persistence.sqlite.recovery_attempt_repository import SqliteRecoveryAttemptRepository
from shea.persistence.sqlite.risk_repository import SqliteRiskAssessmentRepository
from shea.persistence.sqlite.task_repository import SqliteTaskRepository
from shea.persistence.sqlite.tool_execution_repository import SqliteToolExecutionRepository
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from shea.persistence.sqlite.verification_repository import SqliteVerificationRepository
from shea.planning.service import PlanningService
from shea.planning.templates import PlanTemplateRegistry
from shea.ports.execution_boundary import ExecutionBoundary
from shea.ports.model_provider import ModelProvider
from shea.recovery.service import RecoveryService
from shea.security.filesystem_policy import FilesystemPolicy
from shea.security.gate import SecurityGate
from shea.security.injection import PromptInjectionDetector
from shea.security.network_policy import NetworkPolicy
from shea.security.service import SecurityService
from shea.tools.builtin.register import register_builtin_tools
from shea.tools.executor import ToolExecutor
from shea.tools.registry import ToolRegistry
from shea.understanding.deterministic import DeterministicIntentMatcher
from shea.verification.service import VerificationService
from shea.verification.verifier import VerifierRegistry


@dataclass
class SheaRuntime:
    """Process-wide wired graph. Construct once at startup."""

    conn: sqlite3.Connection
    unit_of_work: SqliteUnitOfWork
    orchestrator: Orchestrator
    tool_registry: ToolRegistry
    execution_supervisor: ExecutionSupervisor
    execution_service: ExecutionService
    planning_service: PlanningService
    interaction_service: InteractionService
    plan_runner: PlanRunner
    recovery_service: RecoveryService
    decision_service: DecisionService
    verification_service: VerificationService
    security_service: SecurityService

    def reconcile_app_plane(self) -> list[ReconciliationResult]:
        return self.recovery_service.reconcile_app_plane()


def _filesystem_roots(value: Iterable[str] | None) -> frozenset[str]:
    if value is not None:
        return frozenset(value)
    configured = os.environ.get("SHEA_FILESYSTEM_ROOTS")
    if configured:
        return frozenset(item for item in configured.split(os.pathsep) if item)
    return frozenset({str(Path.cwd())})


def build_runtime(
    db_path: Path | str = ":memory:",
    *,
    workspace: Path | str = "./workspace",
    register_builtins: bool = True,
    filesystem_roots: Iterable[str] | None = None,
    execution_boundary: ExecutionBoundary | None = None,
    allow_unsafe_execution: bool = True,
    include_http_fetch: bool = False,
    model_provider: ModelProvider | None = None,
    register_demo_intents: bool = True,
) -> SheaRuntime:
    """Build the V1 runtime and reconcile unfinished app-plane work.

    ``allow_unsafe_execution`` is intended for local development only. A
    production caller should provide a real execution boundary instead of
    relying on the unsafe fallback in ``ToolExecutor``.
    """
    conn = open_connection(db_path)
    run_migrations(conn)
    unit_of_work = SqliteUnitOfWork(conn)
    clock = SystemClock()
    id_generator = UuidIdGenerator()

    task_repository = SqliteTaskRepository(conn, unit_of_work=unit_of_work)
    plan_repository = SqlitePlanRepository(conn, unit_of_work=unit_of_work)
    audit_sink = SqliteAuditSink(conn, unit_of_work=unit_of_work)
    audit = AuditRecorder(sink=audit_sink, clock=clock, id_generator=id_generator)
    orchestrator = Orchestrator(
        task_repository=task_repository,
        audit=audit,
        clock=clock,
        id_generator=id_generator,
        unit_of_work=unit_of_work,
    )
    provider = model_provider if model_provider is not None else model_provider_from_env()

    decision_repository = SqliteDecisionRepository(conn, unit_of_work=unit_of_work)
    risk_repository = SqliteRiskAssessmentRepository(conn, unit_of_work=unit_of_work)
    authorization_repository = SqliteAuthorizationRepository(conn, unit_of_work=unit_of_work)
    intent_repository = SqliteIntentRepository(conn, unit_of_work=unit_of_work)
    tool_execution_repository = SqliteToolExecutionRepository(
        conn, unit_of_work=unit_of_work
    )
    verification_repository = SqliteVerificationRepository(conn, unit_of_work=unit_of_work)
    recovery_attempt_repository = SqliteRecoveryAttemptRepository(
        conn, unit_of_work=unit_of_work
    )

    registry = ToolRegistry()
    workspace = Path(workspace).resolve() if not isinstance(workspace, Path) else workspace
    workspace.mkdir(parents=True, exist_ok=True)
    matcher = DeterministicIntentMatcher()
    templates = PlanTemplateRegistry()
    network_policy = NetworkPolicy()
    configured_roots = filesystem_roots if filesystem_roots is not None else (str(workspace),)
    filesystem_policy = FilesystemPolicy(
        allowed_roots=_filesystem_roots(configured_roots)
    )
    verifier_registry = VerifierRegistry()
    if register_builtins and register_demo_intents:
        register_builtin_tools(
            registry,
            filesystem_policy=filesystem_policy,
            network_policy=network_policy,
            verifier_registry=verifier_registry,
            include_http_fetch=include_http_fetch,
        )
        register_demo_intent(matcher, templates, workspace=workspace)
    tool_executor = ToolExecutor(
        registry,
        boundary=execution_boundary,
        allow_unsafe_execution=allow_unsafe_execution,
    )

    receipt_repository = SqliteAppReceiptRepository(conn, unit_of_work=unit_of_work)
    attempt_repository = SqliteAppAttemptRepository(conn, unit_of_work=unit_of_work)
    evidence_repository = SqliteAppEvidenceRepository(conn, unit_of_work=unit_of_work)
    app_verification_repository = SqliteAppVerificationRepository(
        conn, unit_of_work=unit_of_work
    )
    idempotency_repository = SqliteAppIdempotencyRepository(
        conn, unit_of_work=unit_of_work
    )
    app_recovery_repository = SqliteAppRecoveryRepository(
        conn, unit_of_work=unit_of_work
    )
    supervisor = ExecutionSupervisor(
        adapters=[ToolExecutorAdapter(tool_executor)],
        receipt_repository=receipt_repository,
        attempt_repository=attempt_repository,
        evidence_repository=evidence_repository,
        verification_repository=app_verification_repository,
        idempotency_repository=idempotency_repository,
        recovery_repository=app_recovery_repository,
        identity_resolver=IdentityResolver(),
        identity_revalidator=IdentityRevalidator(),
        clock=clock,
        id_generator=id_generator,
        unit_of_work=unit_of_work,
    )

    decision_service = DecisionService(
        policy_engine=PolicyEngine(),
        risk_engine=RiskEngine(),
        orchestrator=orchestrator,
        decision_repository=decision_repository,
        risk_repository=risk_repository,
        authorization_repository=authorization_repository,
        plan_repository=plan_repository,
        audit=audit,
        clock=clock,
        id_generator=id_generator,
        unit_of_work=unit_of_work,
    )
    security_service = SecurityService(
        gate=SecurityGate(
            network_policy=network_policy,
            filesystem_policy=filesystem_policy,
        ),
        injection_detector=PromptInjectionDetector(),
        orchestrator=orchestrator,
        audit=audit,
        unit_of_work=unit_of_work,
    )
    execution_service = ExecutionService(
        tool_executor=tool_executor,
        execution_supervisor=supervisor,
        orchestrator=orchestrator,
        decision_repository=decision_repository,
        authorization_repository=authorization_repository,
        plan_repository=plan_repository,
        tool_execution_repository=tool_execution_repository,
        audit=audit,
        id_generator=id_generator,
        security_service=security_service,
        unit_of_work=unit_of_work,
        clock=clock,
    )
    verification_service = VerificationService(
        verifier_registry=verifier_registry,
        orchestrator=orchestrator,
        tool_execution_repository=tool_execution_repository,
        verification_repository=verification_repository,
        audit=audit,
        clock=clock,
        id_generator=id_generator,
        unit_of_work=unit_of_work,
    )
    planning_service = PlanningService(
        orchestrator=orchestrator,
        deterministic_matcher=matcher,
        template_registry=templates,
        tool_registry=registry,
        intent_repository=intent_repository,
        plan_repository=plan_repository,
        audit=audit,
        clock=clock,
        id_generator=id_generator,
        unit_of_work=unit_of_work,
        model_provider=provider,
    )
    recovery_service = RecoveryService(
        orchestrator=orchestrator,
        recovery_attempt_repository=recovery_attempt_repository,
        tool_execution_repository=tool_execution_repository,
        verification_repository=verification_repository,
        audit=audit,
        id_generator=id_generator,
        unit_of_work=unit_of_work,
        execution_supervisor=supervisor,
    )
    plan_runner = PlanRunner(
        decision_service=decision_service,
        execution_service=execution_service,
        verification_service=verification_service,
        security_service=security_service,
        plan_repository=plan_repository,
        tool_registry=registry,
    )
    interaction_service = InteractionService(
        planning_service=planning_service,
        plan_runner=plan_runner,
    )

    runtime = SheaRuntime(
        conn=conn,
        unit_of_work=unit_of_work,
        orchestrator=orchestrator,
        tool_registry=registry,
        execution_supervisor=supervisor,
        execution_service=execution_service,
        planning_service=planning_service,
        interaction_service=interaction_service,
        plan_runner=plan_runner,
        recovery_service=recovery_service,
        decision_service=decision_service,
        verification_service=verification_service,
        security_service=security_service,
    )
    runtime.reconcile_app_plane()
    return runtime
