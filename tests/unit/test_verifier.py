from __future__ import annotations

from datetime import UTC, datetime

from shea.contracts.enums import ExecutionOutcome, TaskState
from shea.contracts.models import Task, ToolExecutionRecord
from shea.verification.verifier import VerificationOutcome, VerifierRegistry, default_verifier


def make_task() -> Task:
    return Task(
        id="task-1",
        session_id="session-1",
        request_id="req-1",
        state=TaskState.VERIFYING,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def make_record(**overrides: object) -> ToolExecutionRecord:
    defaults: dict[str, object] = dict(
        id="exec-1",
        task_id="task-1",
        tool="echo",
        action="lookup",
        outcome=ExecutionOutcome.SUCCESS,
        success=True,
    )
    defaults.update(overrides)
    return ToolExecutionRecord(**defaults)  # type: ignore[arg-type]


def test_default_verifier_trusts_successful_report() -> None:
    outcome = default_verifier(make_task(), make_record())
    assert outcome.verified is True
    assert outcome.method == "execution_report"


def test_default_verifier_does_not_trust_failed_report() -> None:
    outcome = default_verifier(
        make_task(), make_record(outcome=ExecutionOutcome.FAILURE, success=False)
    )
    assert outcome.verified is False


def test_registry_returns_default_when_no_tool_specific_verifier() -> None:
    registry = VerifierRegistry()
    verifier = registry.get("unregistered.tool")
    assert verifier is default_verifier


def test_registry_returns_registered_verifier_for_matching_tool() -> None:
    def always_fails(task: Task, record: ToolExecutionRecord) -> VerificationOutcome:
        return VerificationOutcome(verified=False, method="custom", explanation="nope")

    registry = VerifierRegistry()
    registry.register("special.tool", always_fails)

    assert registry.get("special.tool") is always_fails
    assert registry.get("other.tool") is not always_fails