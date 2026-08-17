from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from shea.contracts.enums import ExecutionOutcome
from shea.contracts.models import ToolRequest, ToolResponse
from shea.tools.executor import CapabilityNotAuthorizedError, ToolExecutor
from shea.tools.registry import ToolDeclaration, ToolRegistry

capability_pool = st.sampled_from(
    [
        "filesystem.read",
        "filesystem.write",
        "process.execute",
        "network.connect",
        "network.listen",
        "system.configure",
        "credential.access",
    ]
)

capability_sets = st.frozensets(capability_pool, min_size=0, max_size=4)


@given(required=capability_sets, authorized=capability_sets)
def test_handler_invoked_iff_required_is_subset_of_authorized(
    required: frozenset[str], authorized: frozenset[str]
) -> None:
    """The defining property of "No capability -> No execution": across
    every combination of required vs. authorized capabilities, the
    handler fires exactly when required is a subset of authorized — never
    partially, never "close enough."
    """
    calls: list[ToolRequest] = []

    def handler(request: ToolRequest) -> ToolResponse:
        calls.append(request)
        return ToolResponse(success=True)

    registry = ToolRegistry()
    registry.register(ToolDeclaration(name="tool", capabilities=required), handler)
    executor = ToolExecutor(registry)
    request = ToolRequest(request_id="req-1", tool="tool", action="do_thing")

    should_be_authorized = required <= authorized

    if should_be_authorized:
        result = executor.execute(request, authorized)
        assert len(calls) == 1
        assert result.outcome == ExecutionOutcome.SUCCESS
    else:
        try:
            executor.execute(request, authorized)
        except CapabilityNotAuthorizedError:
            pass
        else:
            raise AssertionError("expected CapabilityNotAuthorizedError")
        assert len(calls) == 0
