from __future__ import annotations

from shea.contracts.models import ToolRequest, ToolResponse
from shea.ports.execution_boundary import BoundaryHandler, ExecutionScope


class UnsafeExecutionBoundary:
    """No sandboxing, no timeout, no redaction — just calls the handler
    directly. This is ToolExecutor's default when no real boundary is
    injected, so "no boundary configured" and "explicitly configured for
    no isolation" are the same code path rather than two.

    Named `Unsafe` deliberately: a production deployment should inject
    shea.security.sandbox.SandboxedExecutionBoundary (or an equivalent)
    instead of relying on this default past local development/tests.
    """

    def run(
        self, request: ToolRequest, handler: BoundaryHandler, scope: ExecutionScope
    ) -> ToolResponse:
        return handler(request)