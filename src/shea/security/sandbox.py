from __future__ import annotations

import concurrent.futures
from typing import Any, cast

from shea.contracts.models import ToolRequest, ToolResponse
from shea.ports.execution_boundary import BoundaryHandler, ExecutionScope
from shea.tools.executor import UnknownOutcomeError

from .secrets import SecretRedactor


class SandboxedExecutionBoundary:
    """Structurally satisfies shea.ports.execution_boundary.ExecutionBoundary.

    This is the "Sandbox" pipeline stage — the OS/runtime-level
    constraints applied to an already-authorized, already-security-cleared
    call. It deliberately does NOT re-check URLs or paths: that's
    SecurityGate/SecurityService's job, run once, upstream of ToolExecutor
    entirely, using the general shape-based scan across all arguments
    rather than this layer's own narrower copy of the same logic. A
    second, different implementation of "does this look dangerous" is
    worse than one — see the Phase 6 review in tasks/todo.md for the bug
    this replaced.

    A real timeout is treated as UNKNOWN, not FAILURE — research doc
    Section 12.13's exact example ("Shea sends payment... Network
    connection dies... Shea never receives response... must not assume
    'Request failed, retry'") applies directly: the handler may have
    completed its side effect before the timeout fired.
    """

    def __init__(self, redactor: SecretRedactor | None = None) -> None:
        self._redactor = redactor or SecretRedactor()

    def run(
        self, request: ToolRequest, handler: BoundaryHandler, scope: ExecutionScope
    ) -> ToolResponse:
        if scope.max_runtime_seconds is not None:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(handler, request)
                try:
                    response = future.result(timeout=scope.max_runtime_seconds)
                except concurrent.futures.TimeoutError as exc:
                    raise UnknownOutcomeError(
                        f"tool {request.tool!r} exceeded the "
                        f"{scope.max_runtime_seconds}s timeout; outcome unknown"
                    ) from exc
        else:
            response = handler(request)

        if scope.redact_secrets:
            response = self._redact_response(response)

        return response

    def _redact_response(self, response: ToolResponse) -> ToolResponse:
        redacted_error = (
            self._redactor.redact(response.error) if response.error else response.error
        )
        
        raw_data = response.data
        if isinstance(raw_data, dict):
            typed_data = cast(dict[str, Any], raw_data)
            redacted_data: Any = self._redactor.redact_mapping(typed_data)
        else:
            redacted_data = raw_data

        return ToolResponse(
            success=response.success,
            data=redacted_data,
            error=redacted_error,
            metadata=response.metadata,
        )