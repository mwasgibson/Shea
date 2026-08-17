from __future__ import annotations

from shea.contracts.models import Decision, RiskAssessment


class PolicyDeniedError(Exception):
    """Raised when a requested capability set is in the deny list.

    This is the non-negotiable tier (research doc Section 15.12): unlike
    AuthorizationRequiredError, there is no `explicit_user_ack` that makes
    this go away. Callers must not catch this and retry with an override
    flag — the whole point of PolicyVerdict.DENIED is that no such flag
    exists.
    """

    def __init__(self, task_id: str, denied_capabilities: frozenset[str]) -> None:
        self.task_id = task_id
        self.denied_capabilities = denied_capabilities
        super().__init__(
            f"Task {task_id!r} denied by policy: capabilities {sorted(denied_capabilities)} "
            "are not permitted under any authorization."
        )


class AuthorizationRequiredError(Exception):
    """Raised when a task needs an explicit user acknowledgement that
    hasn't been provided yet. Unlike PolicyDeniedError, this IS
    overridable — the caller re-invokes DecisionService with
    `explicit_user_ack=True` once the user has actually decided.

    Carries the Decision and RiskAssessment so the caller (CLI, API,
    whatever) has what it needs to present the warning to the user without
    a second round-trip to the repositories.
    """

    def __init__(self, task_id: str, decision: Decision, risk_assessment: RiskAssessment) -> None:
        self.task_id = task_id
        self.decision = decision
        self.risk_assessment = risk_assessment
        super().__init__(
            f"Task {task_id!r} requires explicit user acknowledgement "
            f"(risk={risk_assessment.level.value}): {risk_assessment.explanation}"
        )


__all__ = ["PolicyDeniedError", "AuthorizationRequiredError"]