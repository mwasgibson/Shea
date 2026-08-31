from __future__ import annotations


class PlanValidationError(Exception):
    """Raised when a candidate Plan fails structural validation — empty
    steps, a step with no tool, or a step referencing a tool that isn't
    registered. This is the concrete enforcement of research doc Section
    6.5's hard boundary: "A plan should not execute simply because an LLM
    produced it." Passing this check is necessary but not sufficient for
    execution — DecisionService's authorization is still required
    downstream; this only confirms the plan is well-formed and
    referentially valid.
    """

    def __init__(self, plan_id: str, reason: str) -> None:
        self.plan_id = plan_id
        self.reason = reason
        super().__init__(f"Plan {plan_id!r} failed validation: {reason}")