from __future__ import annotations

import concurrent.futures
import json
from typing import Any

from shea.contracts.models import ToolRequest, ToolResponse
from shea.ports.execution_boundary import BoundaryHandler, ExecutionScope
from shea.tools.executor import UnknownOutcomeError

from .secrets import SecretRedactor


class SandboxedExecutionBoundary:
    """In-process *resource* boundary — not a full OS sandbox.

    Pipeline position:
        SecurityGate → (adapter OS isolation) → this boundary → handler

    Responsibilities here:
      - wall-clock timeout → UNKNOWN (side effect may have occurred)
      - secret redaction of response
      - max output size

    OS isolation (setsid, rlimits, NO_NEW_PRIVS) applies when an adapter
    spawns a child via ``shea.security.isolation.make_preexec_fn``.
    In-process tool handlers cannot be setsid'd; they only get timeout /
    redaction / output caps from this class.
    """

    def __init__(self, redactor: SecretRedactor | None = None) -> None:
        self._redactor = redactor or SecretRedactor()

    def run(
        self, request: ToolRequest, handler: BoundaryHandler, scope: ExecutionScope
    ) -> ToolResponse:
        timeout = scope.max_runtime_seconds
        if timeout is not None:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(handler, request)
                try:
                    response = future.result(timeout=timeout)
                except concurrent.futures.TimeoutError as exc:
                    raise UnknownOutcomeError(
                        f"tool {request.tool!r} exceeded the "
                        f"{timeout}s timeout; outcome unknown"
                    ) from exc
        else:
            response = handler(request)

        if scope.redact_secrets:
            response = self._redact_response(response)

        if scope.max_output_bytes is not None and response.data is not None:
            size = self._estimate_size(response.data)
            if size > scope.max_output_bytes:
                return ToolResponse(
                    success=False,
                    data=None,
                    error=(
                        f"tool output exceeded max_output_bytes "
                        f"({size} > {scope.max_output_bytes})"
                    ),
                    metadata={
                        **dict(response.metadata),
                        "output_truncated": True,
                        "isolation_layer": "resource_boundary",
                    },
                )

        meta = dict(response.metadata)
        meta["isolation_layer"] = "resource_boundary"
        meta["isolation_limits"] = {
            "max_runtime_seconds": scope.max_runtime_seconds,
            "max_output_bytes": scope.max_output_bytes,
            "redact_secrets": scope.redact_secrets,
        }
        return ToolResponse(
            success=response.success,
            data=response.data,
            error=response.error,
            metadata=meta,
        )

    def _redact_response(self, response: ToolResponse) -> ToolResponse:
        data = response.data
        error = response.error
        if isinstance(data, str):
            data = self._redactor.redact(data)
        elif data is not None:
            try:
                blob = json.dumps(data, default=str)
                redacted = self._redactor.redact(blob)
                data = json.loads(redacted)
            except (TypeError, ValueError):
                data = self._redactor.redact(str(data))
        if isinstance(error, str):
            error = self._redactor.redact(error)
        return ToolResponse(
            success=response.success,
            data=data,
            error=error,
            metadata=dict(response.metadata),
        )

    @staticmethod
    def _estimate_size(data: Any) -> int:
        if isinstance(data, (bytes, bytearray)):
            return len(data)
        if isinstance(data, str):
            return len(data.encode())
        try:
            return len(json.dumps(data, default=str).encode())
        except (TypeError, ValueError):
            return len(str(data).encode())