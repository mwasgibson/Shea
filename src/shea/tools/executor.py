from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from shea.contracts.enums import ExecutionOutcome
from shea.contracts.models import ToolRequest, ToolResponse
from shea.ports.execution_boundary import ExecutionBoundary, ExecutionScope

from .boundary import UnsafeExecutionBoundary
from .registry import ToolDeclaration, ToolRegistry
from .schema import ArgumentSchema, ArgumentType, ToolSchema


class UnknownOutcomeError(Exception):
    """A tool handler raises this to explicitly signal that it cannot
    determine whether its side effect occurred — e.g. a connection
    dropped after an action was sent but before a result was received
    (research doc Section 12.13). This is NOT a generic exception type:
    handlers must not raise it as a catch-all, only when they genuinely
    cannot distinguish success from failure. Any other exception a
    handler raises is treated as a definite FAILURE.

    Boundary implementations (e.g. a timeout) should raise this too, for
    the same reason: a timed-out call may have completed its side effect
    before the timeout fired, so "timeout" is UNKNOWN, not FAILURE.
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


class UnsafeExecutionNotAllowedError(Exception):
    """Raised when ToolExecutor is constructed with no boundary and no
    explicit `allow_unsafe_execution=True`.

    Audit finding (see tasks/todo.md Phase 8): `ToolExecutor(registry)`
    used to silently default to no isolation at all — a convention
    ("production should inject a real boundary") rather than a mechanical
    guarantee. This makes the unsafe path something a caller has to name
    out loud, matching the same "no silent bypass" standard the
    capability gate and security gate already hold themselves to.
    """

    def __init__(self) -> None:
        super().__init__(
            "ToolExecutor requires either a real ExecutionBoundary or "
            "allow_unsafe_execution=True — there is no silent unsafe default."
        )


class ToolExecutor:
    """Technical doc Component: Tool Executor ("Executes validated tool
    requests"), implementing the pipeline fragment from Section 5.1:
    Tool Layer -> Execution, with the capability check as a hard gate
    before the handler is ever reached.

    Exactly one call site invokes a handler: `self._boundary.run(...)`.
    There is no fallback path that calls the handler directly, so a
    configured boundary can never be silently bypassed by a leftover
    branch. Unlike Phases 1-7, "no boundary configured" is no longer
    treated the same as "explicitly configured for no isolation" — the
    latter now requires `allow_unsafe_execution=True` to be spelled out
    at the call site (see UnsafeExecutionNotAllowedError).
    """

    def __init__(
        self,
        registry: ToolRegistry,
        boundary: ExecutionBoundary | None = None,
        *,
        allow_unsafe_execution: bool = False,
    ) -> None:
        self._registry = registry
        if boundary is None:
            if not allow_unsafe_execution:
                raise UnsafeExecutionNotAllowedError()
            boundary = UnsafeExecutionBoundary()
        self._boundary: ExecutionBoundary = boundary
        self._schema_cache: dict[str, ToolSchema | None] = {}

    def execute(
        self,
        request: ToolRequest,
        authorized_capabilities: frozenset[str],
        scope: ExecutionScope | None = None,
    ) -> ExecutionResult:
        declaration = self._registry.get_declaration(request.tool)

        missing = declaration.capabilities - authorized_capabilities
        if missing:
            # Deliberately raised before any handler lookup or call —
            # there is no code path here that reaches the handler once
            # this check fails.
            raise CapabilityNotAuthorizedError(request.tool, missing)

        validated_request = self._validate_arguments(request, declaration)
        handler = self._registry.get_handler(request.tool)
        effective_scope = scope or ExecutionScope()

        try:
            response = self._boundary.run(validated_request, handler, effective_scope)
        except UnknownOutcomeError as exc:
            return ExecutionResult(
                response=ToolResponse(success=False, error=str(exc)),
                outcome=ExecutionOutcome.UNKNOWN,
            )
        except Exception as exc:
            # Deliberately broad: any unexpected exception from the
            # boundary or the handler it wraps is a definite FAILURE, not
            # a crash of the executor itself.
            return ExecutionResult(
                response=ToolResponse(success=False, error=str(exc)),
                outcome=ExecutionOutcome.FAILURE,
            )

        outcome = ExecutionOutcome.SUCCESS if response.success else ExecutionOutcome.FAILURE
        return ExecutionResult(response=response, outcome=outcome)

    def validate_capabilities(
        self,
        request: ToolRequest,
        authorized_capabilities: frozenset[str],
    ) -> None:
        missing = (
            self._registry.get_declaration(request.tool).capabilities
            - authorized_capabilities
        )
        if missing:
            raise CapabilityNotAuthorizedError(request.tool, missing)
    
    def _validate_arguments(
        self, request: ToolRequest, declaration: ToolDeclaration
    ) -> ToolRequest:
        """Validate tool arguments against the declared schema and return
        a request with declared defaults actually applied.

        No schema on the declaration means no validation (tools stay
        open) — the original request is returned unchanged. An explicit
        empty schema still rejects unknown arguments.

        Previously called `get_validated_arguments()` purely for its
        side effect of raising on failure and discarded the defaulted
        arguments it returned, so a schema's `default=` for a missing
        optional argument was validated as present but never actually
        reached the handler. Returning (and using) the result closes
        that gap.
        """
        schema = self._get_schema(declaration)
        if schema is None:
            return request
        validated_arguments = schema.get_validated_arguments(request)
        if validated_arguments == request.arguments:
            return request
        return replace(request, arguments=validated_arguments)


    def _get_schema(self, declaration: ToolDeclaration) -> ToolSchema | None:
        """Get or create ToolSchema from declaration's argument_schema."""
        if declaration.name in self._schema_cache:
            return self._schema_cache[declaration.name]

        declared_schema = declaration.argument_schema

        # No schema declared → skip validation entirely
        if declared_schema is None:
            self._schema_cache[declaration.name] = None
            return None

        if isinstance(declared_schema, ToolSchema):
            schema = declared_schema
        else:
            arguments: dict[str, ArgumentSchema] = {
                arg_name: self._parse_argument_schema(arg_name, arg_def)
                for arg_name, arg_def in declared_schema.items()
            }
            schema = ToolSchema(
                name=declaration.name,
                description=declaration.description,
                arguments=arguments,
                required_capabilities=declaration.capabilities,
                baseline_risk=declaration.baseline_risk.value,
                isolation_required=declaration.isolation_required,
                audit_required=declaration.audit_required,
        )

        self._schema_cache[declaration.name] = schema
        return schema

    def _parse_argument_schema(
        self, name: str, arg_def: Mapping[str, Any]
    ) -> ArgumentSchema:
        """Parse a dictionary argument definition into an ArgumentSchema."""
        arg_type = ArgumentType(str(arg_def.get("type", "any")).lower())

        return ArgumentSchema(
            name=name,
            type=arg_type,
            description=str(arg_def.get("description", "")),
            required=bool(arg_def.get("required", True)),
            default=arg_def.get("default"),
            min_value=arg_def.get("min_value"),
            max_value=arg_def.get("max_value"),
            min_length=arg_def.get("min_length"),
            max_length=arg_def.get("max_length"),
            pattern=arg_def.get("pattern"),
            enum=arg_def.get("enum"),
        )