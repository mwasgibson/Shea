from __future__ import annotations

import time

from shea.contracts.models import ToolRequest, ToolResponse
from shea.ports.execution_boundary import ExecutionScope
from shea.security.sandbox import SandboxedExecutionBoundary
from shea.tools.boundary import UnsafeExecutionBoundary
from shea.tools.executor import UnknownOutcomeError


def make_request() -> ToolRequest:
    return ToolRequest(request_id="req-1", tool="test.tool", action="do_thing")


def test_unsafe_boundary_calls_handler_directly() -> None:
    calls: list[ToolRequest] = []

    def handler(request: ToolRequest) -> ToolResponse:
        calls.append(request)
        return ToolResponse(success=True, data="ok")

    boundary = UnsafeExecutionBoundary()
    response = boundary.run(make_request(), handler, ExecutionScope())

    assert len(calls) == 1
    assert response.data == "ok"


def test_sandboxed_boundary_runs_handler_without_timeout() -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True, data="ok")

    boundary = SandboxedExecutionBoundary()
    response = boundary.run(make_request(), handler, ExecutionScope(redact_secrets=False))

    assert response.success is True
    assert response.data == "ok"


def test_sandboxed_boundary_completes_within_timeout() -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True, data="fast")

    boundary = SandboxedExecutionBoundary()
    response = boundary.run(
        make_request(), handler, ExecutionScope(max_runtime_seconds=1.0, redact_secrets=False)
    )

    assert response.data == "fast"


def test_sandboxed_boundary_raises_unknown_outcome_on_timeout() -> None:
    def slow_handler(request: ToolRequest) -> ToolResponse:
        time.sleep(0.3)
        return ToolResponse(success=True)

    boundary = SandboxedExecutionBoundary()

    try:
        boundary.run(make_request(), slow_handler, ExecutionScope(max_runtime_seconds=0.05))
    except UnknownOutcomeError:
        pass
    else:
        raise AssertionError("expected UnknownOutcomeError on timeout")


def test_sandboxed_boundary_redacts_response_data() -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True, data={"key": "AKIAABCDEFGHIJKLMNOP"})

    boundary = SandboxedExecutionBoundary()
    response = boundary.run(make_request(), handler, ExecutionScope(redact_secrets=True))

    assert "AKIAABCDEFGHIJKLMNOP" not in str(response.data)


def test_sandboxed_boundary_redacts_error_message() -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=False, error="failed using key AKIAABCDEFGHIJKLMNOP")

    boundary = SandboxedExecutionBoundary()
    response = boundary.run(make_request(), handler, ExecutionScope(redact_secrets=True))

    assert response.error is not None
    assert "AKIAABCDEFGHIJKLMNOP" not in response.error


def test_sandboxed_boundary_skips_redaction_when_disabled() -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=True, data={"key": "AKIAABCDEFGHIJKLMNOP"})

    boundary = SandboxedExecutionBoundary()
    response = boundary.run(make_request(), handler, ExecutionScope(redact_secrets=False))

    assert response.data == {"key": "AKIAABCDEFGHIJKLMNOP"}