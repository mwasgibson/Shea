from __future__ import annotations

from shea.contracts.models import ToolRequest, ToolResponse
from shea.tools.registry import ToolDeclaration, ToolRegistry
from shea.decision.risk import RiskLevel


def register_interaction_tools(registry: ToolRegistry) -> None:
    def handle_reply(request: ToolRequest) -> ToolResponse:
        message = request.arguments.get("message")
        if not message or not isinstance(message, str):
            return ToolResponse(success=False, error="Argument 'message' must be a string.", data=None)
            
        # The GUI's SSE stream picks up the ToolExecutionRecord and displays the data
        return ToolResponse(success=True, data=message, error=None)
            
    _REPLY_SCHEMA: dict[str, dict[str, object]] = {
        "message": {
            "type": "string",
            "required": True,
            "description": "The message to send to the user."
        }
    }

    declaration = ToolDeclaration(
        name="system.reply",
        description="Send a text message back to the user to communicate conversationally, answer questions, or explain your actions.",
        capabilities=frozenset(["network.local"]),
        baseline_risk=RiskLevel.LOW,
        argument_schema=_REPLY_SCHEMA,
    )
    
    registry.register(
        declaration=declaration,
        handler=handle_reply,
    )