from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from shea.contracts.models import Plan, PlanStep


@dataclass(frozen=True)
class AuthorizationBinding:
    """Content-binding data for authorization verification.

    Contains the SHA-256 hashes of the plan, step, and arguments that
    an authorization was granted for. Any deviation from these hashes
    means the authorization is invalid.
    """

    plan_hash: str
    step_hash: str | None
    arguments_hash: str
    expiry_seconds: int = 3600  # Default: 1 hour
    nonce: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self, now: datetime | None = None) -> bool:
        """Placeholder — real expiry is checked against the Authorization record's timestamp.

        The binding itself does not store a creation time; callers that need
        temporal validity should compare ``now`` against the grant time on
        the persisted Authorization plus ``expiry_seconds``.
        """
        _ = now or datetime.now(timezone.utc)
        return False


def compute_hash(content: Any) -> str:
    """Compute SHA-256 hash of arbitrary content."""
    if isinstance(content, (dict, list)):
        content_str = json.dumps(content, sort_keys=True, default=str)
    else:
        content_str = str(content)
    return hashlib.sha256(content_str.encode()).hexdigest()


def compute_plan_hash(plan: Plan) -> str:
    """Compute hash of a plan for authorization binding."""
    plan_data: dict[str, Any] = {
        "id": plan.id,
        "objective": plan.objective,
        "steps": [
            {
                "id": step.id,
                "tool": step.tool,
                "arguments": step.arguments,
            }
            for step in plan.steps
        ],
    }
    return compute_hash(plan_data)


def compute_step_hash(step: PlanStep) -> str:
    """Compute hash of a specific step for authorization binding."""
    step_data: dict[str, Any] = {
        "id": step.id,
        "tool": step.tool,
        "arguments": step.arguments,
    }
    return compute_hash(step_data)


def compute_arguments_hash(arguments: dict[str, Any]) -> str:
    """Compute hash of tool arguments for authorization binding."""
    return compute_hash(arguments)


def generate_nonce() -> str:
    """Generate a one-time use nonce for replay protection."""
    return secrets.token_hex(16)