from __future__ import annotations

from shea.contracts.enums import RiskLevel
from shea.contracts.models import ToolRequest, ToolResponse
from shea.tools.registry import ToolDeclaration, ToolRegistry


def register_interaction_tools(registry: ToolRegistry) -> None:
    """Registers `system.reply` — a pure echo of its `message` argument,
    used as the final step of a task-path Plan to deliver a
    conversational reply back to the user (see planning/service.py's
    `_build_plan_prompt`). Deliberately not involved in the fast
    conversational path (`PlanningService.answer_conversationally`),
    which never builds a Plan at all."""

    def handle_system_reply(request: ToolRequest) -> ToolResponse:
        message = request.arguments.get("message")
        if not message or not isinstance(message, str):
            return ToolResponse(
                success=False, error="Argument 'message' must be a string.", data=None
            )
        return ToolResponse(success=True, data=message, error=None)

    schema: dict[str, dict[str, object]] = {
        "message": {
            "type": "string",
            "required": True,
            "description": "The message to deliver back to the user.",
        }
    }

    declaration = ToolDeclaration(
        name="system.reply",
        description="Deliver a conversational reply, summary, or result back to the user.",
        capabilities=frozenset(["network.local"]),
        baseline_risk=RiskLevel.LOW,
        argument_schema=schema,
    )

    registry.register(declaration=declaration, handler=handle_system_reply)
