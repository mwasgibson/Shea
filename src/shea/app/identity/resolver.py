from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from shea.app.exceptions import ContractValidationError
from shea.app.identities import (
    IdentityKind,
    IdentityRequirements,
    RequestedTarget,
    ResolvedIdentity,
)


class IdentityResolver:
    """Resolve a requested target without invoking a side effect (EP §6.2 step 4)."""

    def resolve(
        self,
        target: RequestedTarget,
        requirements: IdentityRequirements,
    ) -> ResolvedIdentity:
        if target.kind not in requirements.allowed_kinds:
            raise ContractValidationError(
                f"target kind {target.kind.value} not allowed by identity requirements"
            )

        if target.kind is IdentityKind.PATH:
            expanded = os.path.expanduser(target.value)
            canonical = str(Path(expanded).resolve(strict=False))
            return ResolvedIdentity(
                kind=IdentityKind.PATH,
                canonical_value=canonical,
                requested_value=target.value,
                attributes={"expanded": expanded},
            )

        if target.kind is IdentityKind.HOST:
            host = target.value.strip().lower()
            if not host:
                raise ContractValidationError("empty host target")
            return ResolvedIdentity(
                kind=IdentityKind.HOST,
                canonical_value=host,
                requested_value=target.value,
            )

        if target.kind is IdentityKind.URL:
            parsed = urlparse(target.value)
            if not parsed.scheme or not parsed.hostname:
                raise ContractValidationError(f"invalid URL target: {target.value!r}")
            return ResolvedIdentity(
                kind=IdentityKind.URL,
                canonical_value=target.value,
                requested_value=target.value,
                attributes={
                    "scheme": parsed.scheme.lower(),
                    "host": parsed.hostname.lower(),
                },
            )

        if target.kind is IdentityKind.PROCESS:
            # Numeric PID is not durable identity; record as requested only.
            return ResolvedIdentity(
                kind=IdentityKind.PROCESS,
                canonical_value=target.value,
                requested_value=target.value,
                attributes=dict(target.attributes),
            )

        return ResolvedIdentity(
            kind=target.kind,
            canonical_value=target.value,
            requested_value=target.value,
            attributes=dict(target.attributes),
        )