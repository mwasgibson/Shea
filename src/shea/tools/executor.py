from __future__ import annotations

from dataclasses import dataclass

from shea.contracts.enums import ExecutionOutcome
from shea.contracts.models import ToolRequest, ToolResponse

from .registry import ToolRegistry


class UnknownOutcomeError(Exception):
    """A tool handler raises this to explicitly signal that it cannot
    determine whether its side effect occurred — e.g. a connection
    dropped after an action was sent but before a result was received
    (research doc Section 12.13). This is NOT a generic exception type:
    handlers must not raise it as a catch-all, only when they genuinely
    cannot distinguish success from failure. Any other exception a
    handler raises is treated as a definite FAILURE.
    """


class CapabilityNotAuthorizedError(Exception):
    """Raised when a tool's declared capabilities are not a subset of
    what was authorized for this invocation. The handler is NEVER called
    in this case — this is the concrete enforcement of technical doc
    Section 19's property: "An unauthorized tool request must never reach
    the execution backend."
    """

    def __init__(self, tool_name: str, missing_capabilities: frozenset[str]) -> None:
        self.tool_name = tool_name
        self.missing_capabilities = missing_capabilities
        super().__init__(
            f"Tool {tool_name!r} requires capabilities "
            f"{sorted(missing_capabilities)} that were not authorized for this task"
        )


@dataclass(frozen=True)
class ExecutionResult:
    response: ToolResponse
    outcome: ExecutionOutcome


class ToolExecutor:
    """Technical doc Component: Tool Executor ("Executes validated tool
    requests"), implementing the pipeline fragment from Section 5.1:
    Tool Layer -> Execution, with the capability check as a hard gate
    before the handler is ever reached.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def execute(
        self, request: ToolRequest, authorized_capabilities: frozenset[str]
    ) -> ExecutionResult:
        declaration = self._registry.get_declaration(request.tool)

        missing = declaration.capabilities - authorized_capabilities
        if missing:
            # Deliberately raised before any handler lookup or call —
            # there is no code path here that reaches the handler once
            # this check fails.
            raise CapabilityNotAuthorizedError(request.tool, missing)

        handler = self._registry.get_handler(request.tool)

        try:
            response = handler(request)
        except UnknownOutcomeError as exc:
            return ExecutionResult(
                response=ToolResponse(success=False, error=str(exc)),
                outcome=ExecutionOutcome.UNKNOWN,
            )
        except Exception as exc:
            # Deliberately broad: any unexpected handler exception is a
            # definite FAILURE, not a crash of the executor itself.
            return ExecutionResult(
                response=ToolResponse(success=False, error=str(exc)),
                outcome=ExecutionOutcome.FAILURE,
            )

        outcome = ExecutionOutcome.SUCCESS if response.success else ExecutionOutcome.FAILURE
        return ExecutionResult(response=response, outcome=outcome)