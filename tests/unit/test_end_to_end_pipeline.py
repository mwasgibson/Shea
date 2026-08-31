from __future__ import annotations

from shea.contracts.enums import TaskState
from shea.contracts.models import ToolRequest, ToolResponse
from shea.decision.service import DecisionService
from shea.execution.service import ExecutionService
from shea.planning.capabilities import capabilities_for_plan
from shea.planning.service import PlanningService
from shea.planning.templates import PlanTemplateRegistry, StepBlueprint
from shea.tools.registry import ToolDeclaration, ToolRegistry
from shea.understanding.deterministic import DeterministicIntentMatcher, IntentDraft
from shea.verification.service import VerificationService


def test_full_pipeline_from_raw_text_to_completed(
    planning_service: PlanningService,
    decision_service: DecisionService,
    execution_service: ExecutionService,
    verification_service: VerificationService,
    deterministic_matcher: DeterministicIntentMatcher,
    template_registry: PlanTemplateRegistry,
    tool_registry: ToolRegistry,
) -> None:
    """The capstone test: a raw text request drives every phase built so
    far — Planning, Decision, Execution, Verification — with nothing
    hand-driving the state machine. This is the first test in the whole
    suite where a task reaches COMPLETED purely as a consequence of
    calling the public service methods in the order a real caller would.
    """

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
    execution_outcome = execution_service.execute(decision_outcome.task, tool_request)
    assert execution_outcome.task.state == TaskState.VERIFYING

    verification_result = verification_service.verify(execution_outcome.task)

    assert verification_result.task.state == TaskState.COMPLETED
    assert verification_result.verification.verified is True