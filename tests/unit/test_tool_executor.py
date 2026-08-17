from __future__ import annotations

import pytest

from shea.contracts.enums import ExecutionOutcome
from shea.contracts.models import ToolRequest, ToolResponse
from shea.tools.executor import (
    CapabilityNotAuthorizedError,
    ToolExecutor,
    UnknownOutcomeError,
)
from shea.tools.registry import ToolDeclaration, ToolRegistry


def make_request(tool: str = "test.tool") -> ToolRequest:
    return ToolRequest(request_id="req-1", tool=tool, action="do_thing")


def test_authorized_call_reaches_handler_and_returns_success() -> None:
    calls: list[ToolRequest] = []

    def handler(request: ToolRequest) -> ToolResponse:
        calls.append(request)
        return ToolResponse(success=True, data="ok")

    registry = ToolRegistry()
    registry.register(
        ToolDeclaration(name="test.tool", capabilities=frozenset({"network.connect"})),
        handler,
    )
    executor = ToolExecutor(registry)

    result = executor.execute(
        make_request(), authorized_capabilities=frozenset({"network.connect"})
    )

    assert len(calls) == 1
    assert result.outcome == ExecutionOutcome.SUCCESS
    assert result.response.success is True
    assert result.response.data == "ok"


def test_unauthorized_capability_never_reaches_handler() -> None:
    """The core property: "No capability -> No execution." The handler
    must never be invoked when the tool's declared capabilities aren't a
    subset of what was authorized.
    """
    calls: list[ToolRequest] = []

    def handler(request: ToolRequest) -> ToolResponse:
        calls.append(request)
        return ToolResponse(success=True)

    registry = ToolRegistry()
    registry.register(
        ToolDeclaration(name="test.tool", capabilities=frozenset({"credential.access"})),
        handler,
    )
    executor = ToolExecutor(registry)

    with pytest.raises(CapabilityNotAuthorizedError) as exc_info:
        executor.execute(make_request(), authorized_capabilities=frozenset({"weather.lookup"}))

    assert len(calls) == 0
    assert exc_info.value.missing_capabilities == frozenset({"credential.access"})


def test_partial_capability_authorization_still_blocks() -> None:
    """A tool needing two capabilities with only one authorized must
    still be blocked entirely — no partial execution.
    """
    calls: list[ToolRequest] = []

    def handler(request: ToolRequest) -> ToolResponse:
        calls.append(request)
        return ToolResponse(success=True)

    registry = ToolRegistry()
    registry.register(
        ToolDeclaration(
            name="test.tool", capabilities=frozenset({"network.connect", "filesystem.write"})
        ),
        handler,
    )
    executor = ToolExecutor(registry)

    with pytest.raises(CapabilityNotAuthorizedError) as exc_info:
        executor.execute(
            make_request(), authorized_capabilities=frozenset({"network.connect"})
        )

    assert len(calls) == 0
    assert exc_info.value.missing_capabilities == frozenset({"filesystem.write"})


def test_handler_returning_success_false_is_failure_outcome() -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        return ToolResponse(success=False, error="tool-reported failure")

    registry = ToolRegistry()
    registry.register(ToolDeclaration(name="test.tool", capabilities=frozenset()), handler)
    executor = ToolExecutor(registry)

    result = executor.execute(make_request(), authorized_capabilities=frozenset())

    assert result.outcome == ExecutionOutcome.FAILURE
    assert result.response.success is False


def test_unexpected_exception_is_failure_outcome_not_unknown() -> None:
    def handler(request: ToolRequest) -> ToolResponse:
        raise ValueError("boom")

    registry = ToolRegistry()
    registry.register(ToolDeclaration(name="test.tool", capabilities=frozenset()), handler)
    executor = ToolExecutor(registry)

    result = executor.execute(make_request(), authorized_capabilities=frozenset())

    assert result.outcome == ExecutionOutcome.FAILURE
    assert "boom" in (result.response.error or "")


def test_unknown_outcome_error_is_unknown_not_failure() -> None:
    """Research doc Section 12.13: SUCCESS/FAILURE/UNKNOWN must stay
    distinct. A handler that explicitly cannot determine its outcome must
    surface as UNKNOWN, never silently become FAILURE.
    """

    def handler(request: ToolRequest) -> ToolResponse:
        raise UnknownOutcomeError("connection dropped after send, before confirmation")

    registry = ToolRegistry()
    registry.register(ToolDeclaration(name="test.tool", capabilities=frozenset()), handler)
    executor = ToolExecutor(registry)

    result = executor.execute(make_request(), authorized_capabilities=frozenset())

    assert result.outcome == ExecutionOutcome.UNKNOWN
    assert result.outcome != ExecutionOutcome.FAILURE
