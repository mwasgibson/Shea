from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from shea.app.enums import EvidenceStrength


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    receipt_id: str
    attempt_id: str | None
    kind: str
    source: str
    strength: EvidenceStrength
    observed_at: datetime
    content_hash: str
    payload: dict[str, Any] = field(default_factory=dict[str, Any])
    sensitivity: str = "normal"