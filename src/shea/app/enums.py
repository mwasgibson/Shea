from __future__ import annotations

from enum import Enum


class AppOutcome(Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"


class ReceiptState(Enum):
    CREATED = "CREATED"
    ATTEMPTING = "ATTEMPTING"
    FINALIZED = "FINALIZED"


class AttemptState(Enum):
    CREATED = "CREATED"
    INVOKED = "INVOKED"
    FINALIZED = "FINALIZED"