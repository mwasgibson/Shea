from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from shea.app.enums import AppOutcome, AttemptState, ReceiptState
from shea.app.identities import IdentityKind, IdentityRequirements, RequestedTarget
from shea.app.scopes import ExecutionScope


@dataclass(frozen=True)
class ExecutionContract:
    """Authorized work delivered to the app plane.

    The app plane validates this; it does not invent or broaden authority.
    """

    contract_id: str
    authorization_id: str
    capability: str
    operation: str
    target: str
    arguments: dict[str, Any] = field(default_factory=dict[str, Any])
    contract_hash: str | None = None
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])
    requested_target: RequestedTarget | None = None
    identity_requirements: IdentityRequirements = field(
        default_factory=IdentityRequirements
    )
    scope: ExecutionScope | None = None


@dataclass
class ExecutionReceipt:
    """Durable intent-to-execute; must exist before any adapter invoke."""

    id: str
    contract_id: str
    authorization_id: str
    capability: str
    operation: str
    target: str
    state: ReceiptState
    created_at: datetime
    finalized_at: datetime | None = None
    outcome: AppOutcome | None = None
    adapter_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass
class ExecutionAttempt:
    """One physical invoke under a receipt. Retries = new attempt, same receipt."""

    id: str
    receipt_id: str
    attempt_number: int
    state: AttemptState
    created_at: datetime
    invoked_at: datetime | None = None
    finalized_at: datetime | None = None
    outcome: AppOutcome | None = None
    adapter_name: str | None = None
    error: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class AdapterResult:
    """Facts only — never authority."""

    outcome: AppOutcome
    evidence: dict[str, Any] = field(default_factory=dict[str, Any])
    error: str | None = None
    
def effective_requested_target(contract: ExecutionContract) -> RequestedTarget:
    if contract.requested_target is not None:
        return contract.requested_target
    return RequestedTarget(kind=IdentityKind.OPAQUE, value=contract.target)