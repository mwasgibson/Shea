from __future__ import annotations

from pathlib import Path

from shea.app.exceptions import ContractValidationError
from shea.app.identities import (
    IdentityAssurance,
    IdentityKind,
    IdentityRequirements,
    ResolvedIdentity,
    VerifiedIdentity,
)


class IdentityRevalidator:
    """Verify / revalidate identity at required assurance (EP §6.2 steps 5 & 8)."""

    def verify(
        self,
        resolved: ResolvedIdentity,
        requirements: IdentityRequirements,
        *,
        phase: str = "pre_receipt",
    ) -> VerifiedIdentity:
        assurance = requirements.assurance

        if resolved.kind is IdentityKind.PATH:
            return self._verify_path(resolved, assurance, phase)

        if resolved.kind in (IdentityKind.HOST, IdentityKind.URL, IdentityKind.OPAQUE):
            return VerifiedIdentity(
                identity=resolved,
                assurance=assurance,
                verified=True,
                method=f"{phase}:literal",
                detail="literal identity accepted at BASIC+",
            )

        if resolved.kind is IdentityKind.PROCESS:
            if assurance in (
                IdentityAssurance.STRICT,
                IdentityAssurance.INTEGRITY,
                IdentityAssurance.HIGH_ASSURANCE,
            ):
                # PID alone is insufficient at STRICT+
                if "executable" not in resolved.attributes:
                    raise ContractValidationError(
                        "process identity requires executable attribute at STRICT+"
                    )
            return VerifiedIdentity(
                identity=resolved,
                assurance=assurance,
                verified=True,
                method=f"{phase}:process_attrs",
                detail="process identity attributes present",
            )

        raise ContractValidationError(
            f"unsupported identity kind for verification: {resolved.kind.value}"
        )

    def _verify_path(
        self,
        resolved: ResolvedIdentity,
        assurance: IdentityAssurance,
        phase: str,
    ) -> VerifiedIdentity:
        path = Path(resolved.canonical_value)

        if assurance is IdentityAssurance.BASIC:
            return VerifiedIdentity(
                identity=resolved,
                assurance=assurance,
                verified=True,
                method=f"{phase}:path_canonical",
                detail=str(path),
            )

        # STRICT+: parent must exist (target itself may be created later)
        parent = path.parent
        if not parent.exists():
            raise ContractValidationError(
                f"path parent does not exist for STRICT+ identity: {parent}"
            )

        if assurance in (IdentityAssurance.INTEGRITY, IdentityAssurance.HIGH_ASSURANCE):
            if path.exists() and path.is_symlink():
                raise ContractValidationError(
                    f"symlink target rejected at {assurance.value}: {path}"
                )

        return VerifiedIdentity(
            identity=resolved,
            assurance=assurance,
            verified=True,
            method=f"{phase}:path_{assurance.value.lower()}",
            detail=str(path.resolve()) if path.exists() else str(path),
        )