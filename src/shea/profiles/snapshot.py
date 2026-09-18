from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast


@dataclass(frozen=True)
class ProfileSnapshot:
    """Frozen profile context bound to a task for its entire lifetime.

    Live ProfileService lookups must not be used mid-task. Switching the
    active profile must not change credentials, memory scope, tools, or
    resource limits for an already-running task.
    """

    profile_id: str
    name: str
    preferences: dict[str, Any] = field(default_factory=dict[str, Any])
    context_rules: dict[str, str] = field(default_factory=dict[str, str])
    frozen_at: datetime | None = None

    def to_parameters(self) -> dict[str, Any]:
        """Serialize into Intent.parameters under a reserved key."""
        return {
            "profile_id": self.profile_id,
            "_profile_snapshot": {
                "profile_id": self.profile_id,
                "name": self.name,
                "preferences": dict(self.preferences),
                "context_rules": dict(self.context_rules),
                "frozen_at": self.frozen_at.isoformat() if self.frozen_at else None,
            },
        }

    @classmethod
    def from_parameters(cls, parameters: dict[str, Any]) -> ProfileSnapshot:
        raw = parameters.get("_profile_snapshot")
        if isinstance(raw, dict):
            snapshot_data = cast(dict[str, Any], raw)
            raw_frozen_at = snapshot_data.get("frozen_at")
            frozen_at: str | None = raw_frozen_at if isinstance(raw_frozen_at, str) else None
            return cls(
                profile_id=str(
                    snapshot_data.get("profile_id")
                    or parameters.get("profile_id")
                    or "system"
                ),
                name=str(snapshot_data.get("name") or "system"),
                preferences=dict(snapshot_data.get("preferences") or {}),
                context_rules=dict(snapshot_data.get("context_rules") or {}),
                frozen_at=datetime.fromisoformat(frozen_at) if isinstance(frozen_at, str) else None,
            )
        # Legacy intents: only profile_id string
        return cls(
            profile_id=str(parameters.get("profile_id") or "system"),
            name=str(parameters.get("profile_id") or "system"),
        )

    @classmethod
    def system(cls, *, now: datetime | None = None) -> ProfileSnapshot:
        return cls(profile_id="system", name="system", frozen_at=now)