from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Time as an injectable dependency.

    Nothing in core/ should call datetime.now() directly — that makes
    timestamps untestable and, per technical doc Section 15.27, security-
    sensitive components (which timestamps feed into via audit) should be
    deterministic given the same inputs.
    """

    def now(self) -> datetime: ...