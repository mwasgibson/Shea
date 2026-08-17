from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from shea.contracts.enums import RiskLevel
from shea.contracts.models import ToolRequest, ToolResponse

ToolHandler = Callable[[ToolRequest], ToolResponse]


@dataclass(frozen=True)
class ToolDeclaration:
    """A tool's capability profile — research doc Section 11.9's worked
    examples (`shell.execute`, `weather.lookup`).

    `capabilities` is the set the ToolExecutor checks against what a
    Decision actually authorized before the handler is ever called —
    this is capability-based security, not "is the user allowed to use
    this tool?" `baseline_risk` is advisory metadata about the tool
    itself (e.g. for registry listings or future risk-engine input); it
    does not substitute for RiskEngine's per-invocation assessment.
    """

    name: str
    capabilities: frozenset[str]
    baseline_risk: RiskLevel = RiskLevel.UNKNOWN
    isolation_required: bool = True
    audit_required: bool = True
    description: str = field(default="")


class ToolNotFoundError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"No tool registered with name {name!r}")


class ToolAlreadyRegisteredError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"A tool named {name!r} is already registered")


class ToolRegistry:
    """Technical doc Component: Tool Registry ("Defines available tools
    and capabilities").

    Deliberately dumb: it stores declarations and handlers and nothing
    else. It does not decide whether a call is authorized — that is
    ToolExecutor's job, using a capability set the Decision subsystem
    already recorded, not anything the registry infers.
    """

    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolDeclaration, ToolHandler]] = {}

    def register(self, declaration: ToolDeclaration, handler: ToolHandler) -> None:
        if declaration.name in self._tools:
            raise ToolAlreadyRegisteredError(declaration.name)
        self._tools[declaration.name] = (declaration, handler)

    def get_declaration(self, name: str) -> ToolDeclaration:
        entry = self._tools.get(name)
        if entry is None:
            raise ToolNotFoundError(name)
        return entry[0]

    def get_handler(self, name: str) -> ToolHandler:
        entry = self._tools.get(name)
        if entry is None:
            raise ToolNotFoundError(name)
        return entry[1]

    def list_tools(self) -> list[ToolDeclaration]:
        return [declaration for declaration, _ in self._tools.values()]