from __future__ import annotations

from datetime import datetime


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
class AuthorizationBindingMismatchError(Exception):
    """Raised when an authorization's content binding doesn't match the current request."""

    def __init__(
        self,
        task_id: str,
        mismatch_type: str,
        expected_hash: str | None,
        actual_hash: str | None,
    ) -> None:
        self.task_id = task_id
        self.mismatch_type = mismatch_type
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        super().__init__(
            f"Authorization binding mismatch for task {task_id!r}: "
            f"{mismatch_type} hash mismatch (expected: {expected_hash}, actual: {actual_hash})"
        )

class AuthorizationExpiredError(Exception):
    """Raised when an authorization has expired."""

    def __init__(self, task_id: str, expired_at: datetime) -> None:
        self.task_id = task_id
        self.expired_at = expired_at
        super().__init__(
            f"Authorization for task {task_id!r} expired at {expired_at.isoformat()}"
        )

class AuthorizationAlreadyUsedError(Exception):
    """Raised when an authorization nonce has already been used (replay protection)."""

    def __init__(self, task_id: str, nonce: str) -> None:
        self.task_id = task_id
        self.nonce = nonce
        super().__init__(
            f"Authorization for task {task_id!r} with nonce {nonce!r} has already been used"
        )