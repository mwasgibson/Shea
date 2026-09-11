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
    

class EvidenceStrength(Enum):
    DIRECT = "DIRECT"
    DERIVED = "DERIVED"
    INFERRED = "INFERRED"


class IdempotencyState(Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    EXPIRED = "EXPIRED"
    CONFLICT = "CONFLICT"


class RecoveryStatus(Enum):
    OPEN = "OPEN"
    RECONCILING = "RECONCILING"
    RESOLVED = "RESOLVED"
    QUARANTINED = "QUARANTINED"