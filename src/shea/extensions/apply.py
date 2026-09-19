from __future__ import annotations

import logging
from typing import Any, cast

from shea.contracts.models import ToolRequest, ToolResponse
from shea.extensions.manifest import ExtensionManifest
from shea.extensions.security import RestrictedRuntimeProxy
from shea.tools.registry import ToolDeclaration

logger = logging.getLogger(__name__)


def apply_declarations(
    runtime: Any,
    manifest: ExtensionManifest,
    declarations: list[dict[str, Any]],
    *,
    handle: Any | None = None
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
        if decl.get("kind") != "tool":
            continue
        if "tools.register" not in manifest.permissions:
            raise PermissionError("tools.register not permitted")
        name = str(decl["name"])
        
        raw_caps = cast(list[Any], decl.get("capabilities") or [])
        caps = frozenset(str(c) for c in raw_caps)
        # capability intersection with manifest
        caps = caps & manifest.capabilities if manifest.capabilities else caps

        def make_handler(tool_name: str, host: Any) -> Any:
            def _handler(request: ToolRequest) -> ToolResponse:
                if host is None:
                    return ToolResponse(success=False, error="extension host missing")
                try:
                    out = host.invoke_tool(tool_name, request.action, dict(request.arguments))
                    return ToolResponse(success=True, data=out)
                except Exception as exc:
                    return ToolResponse(success=False, error=str(exc))
            return _handler

        if handle is not None:
            runtime.tool_registry.register(
                ToolDeclaration(
                    name=name,
                    capabilities=caps or frozenset({f"extension.{manifest.id}"}),
                    description=str(decl.get("description", f"extension:{manifest.id}")),
                ),
                make_handler(name, handle),
            )
    return proxy