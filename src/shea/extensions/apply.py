from __future__ import annotations

import logging
from typing import Any

from shea.extensions.manifest import ExtensionManifest
from shea.extensions.security import RestrictedRuntimeProxy

logger = logging.getLogger(__name__)


def apply_declarations(
    runtime: Any,
    manifest: ExtensionManifest,
    declarations: list[dict[str, Any]],
) -> RestrictedRuntimeProxy:
    """Parent process applies child-declared hooks under the capability proxy."""
    proxy = RestrictedRuntimeProxy(
        runtime,
        manifest.name,
        {
            "permissions": sorted(manifest.permissions),
            "capabilities": sorted(manifest.capabilities),
        },
    )
    for decl in declarations:
        kind = decl.get("kind")
        if kind == "tool":
            # Plugin cannot supply arbitrary callables across process boundary in V1.
            # Tools must be registered by name against parent-approved handlers only,
            # or as remote stubs — V1 logs and skips unknown executable payloads.
            logger.warning(
                "extension %s declared tool %r — remote tool handlers require "
                "host RPC invoke (not auto-registered in V1)",
                manifest.id,
                decl.get("name"),
            )
        elif kind == "event_subscribe":
            if "events.subscribe" not in manifest.permissions:
                raise PermissionError("events.subscribe not permitted")
            # subscription handlers also need RPC; skip with log in V1
            logger.info("extension %s requested subscribe %r", manifest.id, decl.get("pattern"))
        else:
            logger.warning("unknown declaration kind %r from %s", kind, manifest.id)

    return proxy