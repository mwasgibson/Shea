from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from shea.contracts.models import Authorization, Decision


class RecoveryAuthorityError(Exception):
    """Recovery attempted outside RecoveryAuthority bounds."""

    def __init__(self, task_id: str, reason: str) -> None:
        self.task_id = task_id
        self.reason = reason
        super().__init__(f"RecoveryAuthority denied for task {task_id!r}: {reason}")


@dataclass(frozen=True)
class RecoveryAuthority:
    """Bounded authority for recovery actions.

    Recovery cannot broaden what the original Decision/Authorization granted.
    Operations, capabilities, targets, and attempt budget are all capped.
    """

    task_id: str
    authorization_id: str
    capabilities: frozenset[str]
    max_attempts: int
    expires_at: datetime | None
    permitted_operations: frozenset[str]
    plan_hash: str | None = None
    step_hash: str | None = None
    arguments_hash: str | None = None
    profile_id: str = "system"

    # Allowed recovery verbs in V1
    DEFAULT_OPERATIONS: frozenset[str] = frozenset(
        {"retry", "compensate", "reconcile", "resolve_blocked"}
    )

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at

    def allows_operation(self, operation: str) -> bool:
        return operation in self.permitted_operations

    def allows_capability(self, capability: str) -> bool:
        return capability in self.capabilities

    def assert_can(
        self,
        *,
        operation: str,
        now: datetime,
        attempts_made: int,
        required_capabilities: frozenset[str] | None = None,
    ) -> None:
        if self.is_expired(now):
            raise RecoveryAuthorityError(self.task_id, "recovery authority expired")
        if attempts_made >= self.max_attempts:
            raise RecoveryAuthorityError(
                self.task_id,
                f"attempt budget exhausted ({attempts_made}/{self.max_attempts})",
            )
        if not self.allows_operation(operation):
            raise RecoveryAuthorityError(
                self.task_id, f"operation {operation!r} not permitted"
            )
        if required_capabilities:
            missing = required_capabilities - self.capabilities
            if missing:
                raise RecoveryAuthorityError(
                    self.task_id,
                    f"recovery would require capabilities not in original grant: {sorted(missing)}",
                )

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "authorization_id": self.authorization_id,
            "capabilities": sorted(self.capabilities),
            "max_attempts": self.max_attempts,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "permitted_operations": sorted(self.permitted_operations),
            "profile_id": self.profile_id,
            "plan_hash": self.plan_hash,
        }

    @classmethod
    def from_original(
        cls,
        *,
        decision: Decision,
        authorization: Authorization,
        max_attempts: int,
        now: datetime,
        recovery_ttl: timedelta | None = None,
    ) -> RecoveryAuthority:
        """Derive recovery authority strictly from original grant (never broader)."""
        if not authorization.granted:
            raise RecoveryAuthorityError(
                decision.task_id, "original authorization was not granted"
            )
        ttl = recovery_ttl or timedelta(hours=1)
        # Recovery expires at the earlier of auth expiry and recovery TTL.
        candidates = [now + ttl]
        if authorization.expires_at is not None:
            candidates.append(authorization.expires_at)
        expires_at = min(candidates)
        return cls(
            task_id=decision.task_id,
            authorization_id=authorization.id,
            capabilities=frozenset(decision.capabilities),
            max_attempts=max_attempts,
            expires_at=expires_at,
            permitted_operations=cls.DEFAULT_OPERATIONS,
            plan_hash=authorization.plan_hash,
            step_hash=authorization.step_hash,
            arguments_hash=authorization.arguments_hash,
            profile_id=authorization.profile_id or "system",
        )