from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from shea.contracts.enums import ExecutionOutcome
from shea.contracts.models import Task, ToolExecutionRecord


@dataclass(frozen=True)
class VerificationOutcome:
    verified: bool
    method: str
    explanation: str


Verifier = Callable[[Task, ToolExecutionRecord], VerificationOutcome]


def default_verifier(task: Task, record: ToolExecutionRecord) -> VerificationOutcome:
    """Fallback used when no tool-specific Verifier is registered.

    This is a known, documented limitation, not a silent violation of
    Appendix B's "EXECUTION SUCCESS != VERIFIED SUCCESS": in the absence
    of a real independent check (e.g. re-reading the filesystem a tool
    claims to have written to), the safest available fallback is to
    reflect the tool's own report rather than either always-pass or
    always-fail. A tool with a real side effect worth verifying
    independently should register its own Verifier with
    VerifierRegistry.register() rather than relying on this fallback.
    """
    if record.outcome is ExecutionOutcome.SUCCESS and record.success:
        return VerificationOutcome(
            verified=True,
            method="execution_report",
            explanation=(
                "Tool reported success; no independent verifier is registered "
                f"for {record.tool!r}, so the execution report is trusted as-is."
            ),
        )
    return VerificationOutcome(
        verified=False,
        method="execution_report",
        explanation=f"Tool {record.tool!r} did not report success.",
    )


class VerifierRegistry:
    """Per-tool Verifier lookup, mirroring ToolRegistry's shape. Contains
    no verification logic of its own beyond the fallback — the whole
    point is that verification logic lives with the tool that knows what
    "actually happened" means for it, not in a generic engine.
    """

    def __init__(self, default: Verifier = default_verifier) -> None:
        self._default = default
        self._verifiers: dict[str, Verifier] = {}

    def register(self, tool_name: str, verifier: Verifier) -> None:
        self._verifiers[tool_name] = verifier

    def get(self, tool_name: str) -> Verifier:
        return self._verifiers.get(tool_name, self._default)