from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IdentityAssurance(Enum):
    """EP doc §5 — how strongly a target must be bound before invoke."""

    BASIC = "BASIC"
    STRICT = "STRICT"
    INTEGRITY = "INTEGRITY"
    HIGH_ASSURANCE = "HIGH_ASSURANCE"


class IdentityKind(Enum):
    PATH = "PATH"
    PROCESS = "PROCESS"
    HOST = "HOST"
    URL = "URL"
    APPLICATION = "APPLICATION"
    OPAQUE = "OPAQUE"


@dataclass(frozen=True)
class RequestedTarget:
    """What the contract asked for — not yet resolved."""

    kind: IdentityKind
    value: str
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class IdentityRequirements:
    assurance: IdentityAssurance = IdentityAssurance.BASIC
    require_revalidation_before_invoke: bool = True
    allowed_kinds: frozenset[IdentityKind] = frozenset(
        {IdentityKind.PATH, IdentityKind.PROCESS, IdentityKind.HOST, IdentityKind.OPAQUE}
    )


@dataclass(frozen=True)
class ResolvedIdentity:
    """Target after resolution, before assurance checks."""

    kind: IdentityKind
    canonical_value: str
    requested_value: str
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class VerifiedIdentity:
    """Resolved + checked at the required assurance level."""

    identity: ResolvedIdentity
    assurance: IdentityAssurance
    verified: bool
    method: str
    detail: str = ""