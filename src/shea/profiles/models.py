from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class UserProfile:
    id: str
    name: str
    preferences: dict[str, Any] = field(default_factory=dict[str, Any])
    context_rules: dict[str, str] = field(default_factory=dict[str, str])
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def get_context_injection(self) -> str:
        """Returns the profile's background context formatted for the intent layer."""
        if not self.context_rules:
            return ""
        
        rules = [f"- {k}: {v}" for k, v in self.context_rules.items()]
        return "User Context & Preferences:\n" + "\n".join(rules)