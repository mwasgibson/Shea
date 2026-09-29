from __future__ import annotations

import webbrowser

from shea.contracts.enums import RiskLevel
from shea.contracts.models import ToolRequest, ToolResponse
from shea.tools.registry import ToolDeclaration, ToolRegistry


def register_browser_tools(registry: ToolRegistry) -> None:
    def handle_browser_open(request: ToolRequest) -> ToolResponse:
        url = request.arguments.get("url")
        if not url or not isinstance(url, str):
            return ToolResponse(success=False, error="Argument 'url' must be a string.", data=None)
            
        opened = webbrowser.open(url)
        if opened:
            return ToolResponse(success=True, data=f"Opened {url} in default browser.", error=None)
        return ToolResponse(success=False, error=f"Failed to open {url} in browser.", data=None)
            
    _BROWSER_SCHEMA: dict[str, dict[str, object]] = {
        "url": {
            "type": "string",
            "required": True,
            "description": "The URL to open in the system's default web browser."
        }
    }

    declaration = ToolDeclaration(
        name="system.browser_open",
        description="Open a URL in the system's default web browser.",
        capabilities=frozenset(["network.local"]),
        baseline_risk=RiskLevel.LOW,
        argument_schema=_BROWSER_SCHEMA,
    )
    
    registry.register(
        declaration=declaration,
        handler=handle_browser_open,
    )