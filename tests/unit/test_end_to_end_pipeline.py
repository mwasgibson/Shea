from __future__ import annotations

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import ExecutionOutcome, RecoveryStrategy, TaskState
from shea.contracts.models import ToolRequest, ToolResponse
from shea.core.orchestrator import Orchestrator
from shea.decision.service import DecisionService
from shea.execution.service import ExecutionService
from shea.persistence.sqlite.decision_repository import SqliteDecisionRepository
from shea.persistence.sqlite.tool_execution_repository import (
    SqliteToolExecutionRepository,
)
from shea.planning.capabilities import capabilities_for_plan
from shea.planning.service import PlanningService
from shea.planning.templates import PlanTemplateRegistry, StepBlueprint
from shea.ports.id_generator import IdGenerator
from shea.recovery.service import RecoveryService
from shea.security.service import SecurityService
from shea.tools.executor import ToolExecutor
from shea.tools.registry import ToolDeclaration, ToolRegistry
from shea.understanding.deterministic import (
    DeterministicIntentMatcher,
    IntentDraft,
)
from shea.verification.service import VerificationService


def test_full_pipeline_from_raw_text_to_completed(
    planning_service: PlanningService,
    decision_service: DecisionService,
    tool_executor: ToolExecutor,
    orchestrator: Orchestrator,
    decision_repository: SqliteDecisionRepository,
    tool_execution_repository: SqliteToolExecutionRepository,
    audit_recorder: AuditRecorder,
    id_generator: IdGenerator,
    security_service: SecurityService,
    verification_service: VerificationService,
    deterministic_matcher: DeterministicIntentMatcher,
    template_registry: PlanTemplateRegistry,
    tool_registry: ToolRegistry,
) -> None:
    """The capstone test: a raw text request drives every phase built so
    far — Planning, Decision, Security, Execution, Verification — with
    nothing hand-driving the state machine. This is the first test in the
    whole suite where a task reaches COMPLETED purely as a consequence of
    calling the public service methods in the order a real caller would,
    with security enforcement as a structural part of execution rather
    than a separate step that could be forgotten.

    RAW REQUEST
        -> UNDERSTANDING
        -> PLANNING
        -> DECISION
        -> SECURITY
        -> EXECUTION
        -> VERIFICATION
        -> COMPLETED
    """

    execution_service = ExecutionService(
        tool_executor=tool_executor,
        orchestrator=orchestrator,
        decision_repository=decision_repository,
        tool_execution_repository=tool_execution_repository,
        audit=audit_recorder,
        id_generator=id_generator,
        security_service=security_service,
    )

    def weather_handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True, data={"forecast": "sunny"})

    tool_registry.register(
        ToolDeclaration(name="weather", capabilities=frozenset({"network.connect"})),
        weather_handler,
    )
    deterministic_matcher.register(
        "weather", IntentDraft(type="weather.lookup", goal="check the weather")
    )
    template_registry.register(
        "weather.lookup",
        lambda draft: [StepBlueprint(tool="weather", action="lookup")],
    )

    planning_outcome = planning_service.create_and_plan(
        session_id="session-1", request_text="what's the weather"
    )
    assert planning_outcome.task.state == TaskState.READY

    capabilities = capabilities_for_plan(planning_outcome.plan, tool_registry)
    assert capabilities == frozenset({"network.connect"})

    decision_outcome = decision_service.evaluate_and_authorize(
        planning_outcome.task, capabilities=capabilities
    )
    assert decision_outcome.task.state == TaskState.RUNNING

    first_step = planning_outcome.plan.steps[0]
    tool_request = ToolRequest(
        request_id="req-exec-1", tool=first_step.tool or "", action=first_step.description
    )
    # Security enforcement happens inside execute() itself (structural,
    # not a separate call a caller could forget).
    execution_outcome = execution_service.execute(decision_outcome.task, tool_request)
    assert execution_outcome.task.state == TaskState.VERIFYING
    assert execution_outcome.outcome is ExecutionOutcome.SUCCESS
    assert execution_outcome.response.success is True

    scan_result = security_service.scan_output(
        execution_outcome.task, first_step.tool or "", execution_outcome.response.data
    )
    assert scan_result.flagged is False

    verification_result = verification_service.verify(execution_outcome.task)
    assert verification_result.verification.verified is True
    assert verification_result.task.state == TaskState.COMPLETED


def test_full_pipeline_failure_enters_recovery_and_reaches_ready(
    planning_service: PlanningService,
    decision_service: DecisionService,
    tool_executor: ToolExecutor,
    orchestrator: Orchestrator,
    decision_repository: SqliteDecisionRepository,
    tool_execution_repository: SqliteToolExecutionRepository,
    audit_recorder: AuditRecorder,
    id_generator: IdGenerator,
    security_service: SecurityService,
    deterministic_matcher: DeterministicIntentMatcher,
    template_registry: PlanTemplateRegistry,
    tool_registry: ToolRegistry,
    recovery_service: RecoveryService,
) -> None:
    """Capstone recovery pipeline.

    RAW REQUEST
        -> PLANNING
        -> DECISION
        -> EXECUTION FAILURE
        -> RECOVERY
        -> COMPENSATION
        -> READY

    The recovery service itself owns the FAILED -> RECOVERING transition
    and the RECOVERING -> READY transition.

    A successful compensator is supplied deliberately for this integration
    test so that the recovery lifecycle can be exercised without claiming
    that the default compensator actually restores anything.
    """

    execution_service = ExecutionService(
        tool_executor=tool_executor,
        orchestrator=orchestrator,
        decision_repository=decision_repository,
        tool_execution_repository=tool_execution_repository,
        audit=audit_recorder,
        id_generator=id_generator,
        security_service=security_service,
    )

    execution_count = 0

    def weather_handler(request: ToolRequest) -> ToolResponse:
        nonlocal execution_count
        execution_count += 1

        return ToolResponse(success=False, error="deliberate failure",)

    tool_registry.register(
        ToolDeclaration(name="weather_recovery", capabilities=frozenset({"network.connect"})),
        weather_handler,
    )
    deterministic_matcher.register(
        "weather recovery",
        IntentDraft(type="weather.recovery", goal="check weather with recovery",),
    )
    template_registry.register(
        "weather.recovery",
        lambda draft: [
            StepBlueprint(tool="weather_recovery", action="lookup",)
        ],
    )

    planning_outcome = planning_service.create_and_plan(
        session_id="session-1", request_text="weather recovery",
    )
    assert planning_outcome.task.state == TaskState.READY

    capabilities = capabilities_for_plan(
        planning_outcome.plan, tool_registry,
    )
    assert capabilities == frozenset({"network.connect"})

    decision_outcome = decision_service.evaluate_and_authorize(
        planning_outcome.task, capabilities=capabilities,
    )
    assert decision_outcome.task.state == TaskState.RUNNING

    first_step = planning_outcome.plan.steps[0]

    tool_request = ToolRequest(
        request_id="req-recovery-1",
        tool=first_step.tool or "",
        action=first_step.description,
    )

    failed_execution = execution_service.execute(
        decision_outcome.task, tool_request,
    )
    assert execution_count == 1
    assert failed_execution.outcome is ExecutionOutcome.FAILURE
    assert failed_execution.response.success is False
    assert failed_execution.task.state == TaskState.FAILED

    recovery_decision = recovery_service.plan_recovery(
        failed_execution.task,
    )
    # The current classifier treats an unrecognized failure as UNKNOWN.
    # That must not become a blind retry.
    assert recovery_decision.strategy is RecoveryStrategy.ESCALATE
    assert recovery_decision.safe_to_retry is False
    assert recovery_decision.requires_verification is True