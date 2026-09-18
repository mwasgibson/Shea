from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, cast


class ExtensionTrustLevel(StrEnum):
    UNTRUSTED = "UNTRUSTED"
    COMMUNITY = "COMMUNITY"
    TRUSTED = "TRUSTED"
    CORE = "CORE"


class IsolationMode(StrEnum):
    PROCESS = "process"      # default — subprocess host
    INPROCESS = "inprocess"  # only TRUSTED/CORE + explicit env allow


ALLOWED_PERMISSIONS = frozenset({
    "tools.register",
    "events.publish",
    "events.subscribe",
})


@dataclass(frozen=True)
class ExtensionManifest:
    id: str
    name: str
    version: str
    author: str = ""
    api_version: str = "1"
    trust_level: ExtensionTrustLevel = ExtensionTrustLevel.UNTRUSTED
    isolation: IsolationMode = IsolationMode.PROCESS
    permissions: frozenset[str] = field(default_factory=frozenset[str])
    capabilities: frozenset[str] = field(default_factory=frozenset[str])
    dependencies: tuple[str, ...] = ()
    entrypoint: str = "plugin:Plugin"  # module:Class inside plugin dir
    signature: str | None = None  # hex sha256 of canonical body, or external sig
    signature_algorithm: str = "sha256-manifest"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExtensionManifest:
        permission_values: list[Any] = list(data.get("permissions") or [])
        perms = frozenset(str(p) for p in permission_values)
        unknown = perms - ALLOWED_PERMISSIONS
        if unknown:
            raise ValueError(f"unknown permissions: {sorted(unknown)}")
        trust = ExtensionTrustLevel(str(data.get("trust_level", "UNTRUSTED")).upper())
        isolation = IsolationMode(str(data.get("isolation", "process")).lower())
        if isolation is IsolationMode.INPROCESS and trust not in {
            ExtensionTrustLevel.TRUSTED,
            ExtensionTrustLevel.CORE,
        }:
            raise ValueError("inprocess isolation requires trust_level TRUSTED or CORE")
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            version=str(data.get("version", "0.0.0")),
            author=str(data.get("author", "")),
            api_version=str(data.get("api_version", "1")),
            trust_level=trust,
            isolation=isolation,
            permissions=perms,
            capabilities=frozenset(
                str(c) for c in (list(data.get("capabilities") or []))
            ),
            dependencies=tuple(
                str(d) for d in (list(data.get("dependencies") or []))
            ),
            entrypoint=str(data.get("entrypoint", "plugin:Plugin")),
            signature=str(data["signature"]) if data.get("signature") else None,
            signature_algorithm=str(data.get("signature_algorithm", "sha256-manifest")),
        )


def load_manifest(path: Path) -> ExtensionManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest must be a JSON object")
    data = cast(dict[str, Any], raw)
    return ExtensionManifest.from_dict(data)


def canonical_manifest_bytes(data: dict[str, Any]) -> bytes:
    """Stable bytes for signing — signature field excluded."""
    body = {k: v for k, v in data.items() if k not in {"signature", "signature_algorithm"}}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_manifest_signature(path: Path, *, require_signature: bool = False) -> ExtensionManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("manifest must be a JSON object")
    raw = cast(dict[str, Any], raw)
    manifest = ExtensionManifest.from_dict(raw)
    if manifest.signature is None:
        if require_signature or manifest.trust_level is not ExtensionTrustLevel.UNTRUSTED:
            raise ValueError(f"manifest {path} missing signature")
        return manifest
    if manifest.signature_algorithm != "sha256-manifest":
        raise ValueError(f"unsupported signature_algorithm: {manifest.signature_algorithm}")
    expected = hashlib.sha256(canonical_manifest_bytes(raw)).hexdigest()
    if manifest.signature.lower() != expected.lower():
        raise ValueError(f"manifest signature mismatch for {path}")
    return manifest