from __future__ import annotations

import uuid
from datetime import UTC, datetime

from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator


class SystemClock(Clock):
    """Real wall-clock time, always UTC and timezone-aware."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIdGenerator(IdGenerator):
    """UUID4-based identifiers for production use."""

    def new_id(self) -> str:
        return str(uuid.uuid4())