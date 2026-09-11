from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from shea.app.enums import AppOutcome, IdempotencyState


@dataclass
class IdempotencyRecord:
    key: str
    receipt_id: str | None
    state: IdempotencyState
    outcome: AppOutcome | None
    created_at: datetime
    updated_at: datetime