from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PendingConfirmation:
    """Task blocked until explicit user acknowledgement (HIGH/CRITICAL/UNKNOWN)."""

    task_id: str
    session_id: str
    decision_id: str
    risk: str
    explanation: str
    capabilities: list[str]
    created_at: datetime
    acting_user: str = "user"
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


class PendingConfirmationStore:
    """In-process store. Durable enough for a single API process; swap for SQLite later."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_task: dict[str, PendingConfirmation] = {}

    def put(self, pending: PendingConfirmation) -> None:
        with self._lock:
            self._by_task[pending.task_id] = pending

    def get(self, task_id: str) -> PendingConfirmation | None:
        with self._lock:
            return self._by_task.get(task_id)

    def pop(self, task_id: str) -> PendingConfirmation | None:
        with self._lock:
            return self._by_task.pop(task_id, None)

    def list_for_session(self, session_id: str) -> list[PendingConfirmation]:
        with self._lock:
            return [p for p in self._by_task.values() if p.session_id == session_id]