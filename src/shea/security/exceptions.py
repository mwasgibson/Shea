from __future__ import annotations


class SecurityViolationError(Exception):
    """Raised when a tool request fails a pre-execution security check.

    Distinct from PolicyDeniedError (a policy decision about
    capabilities) and CapabilityNotAuthorizedError (a capability gap):
    this represents an active threat pattern detected in the request
    itself. The appropriate response is SECURITY_HALT — a terminal state
    with no automatic recovery path (technical doc Appendix A) — not a
    retry or a warning.
    """

    def __init__(self, tool_name: str, category: str, reason: str) -> None:
        self.tool_name = tool_name
        self.category = category
        self.reason = reason
        super().__init__(f"Security violation ({category}) for tool {tool_name!r}: {reason}")