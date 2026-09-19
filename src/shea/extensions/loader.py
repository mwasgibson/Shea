from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shea.extensions.apply import apply_declarations
from shea.extensions.manifest import IsolationMode, verify_manifest_signature
from shea.extensions.process_host import ProcessExtensionHandle, spawn_extension_host
from shea.extensions.security import RestrictedRuntimeProxy

if TYPE_CHECKING:
    from shea.bootstrap import SheaRuntime

logger = logging.getLogger(__name__)


class PluginLoader:
    def __init__(
        self,
        plugin_dir: str = "plugins",
        *,
        require_signature: bool = False,
        allow_inprocess: bool | None = None,
    ) -> None:
        self.plugin_dir = Path(plugin_dir)
        self.require_signature = require_signature
        if allow_inprocess is None:
            allow_inprocess = os.environ.get("SHEA_ALLOW_INPROCESS_PLUGINS", "") == "1"
        self.allow_inprocess = allow_inprocess
        self._handles: list[ProcessExtensionHandle] = []

    def load_plugins(self, runtime: SheaRuntime) -> list[Any]:
        loaded: list[Any] = []
        if not self.plugin_dir.is_dir():
            return loaded

        for entry in sorted(self.plugin_dir.iterdir()):
            if entry.name.startswith("."):
                continue
            manifest_path = entry / "manifest.json" if entry.is_dir() else None
            if manifest_path is None or not manifest_path.is_file():
                logger.warning("skip %s: no manifest.json (discovery ≠ trust)", entry)
                continue
            try:
                manifest = verify_manifest_signature(
                    manifest_path, require_signature=self.require_signature
                )
            except Exception as exc:
                logger.error("manifest rejected for %s: %s", entry, exc)
                continue

            try:
                if manifest.isolation is IsolationMode.PROCESS:
                    handle = spawn_extension_host(manifest, entry)
                    self._handles.append(handle)
                    apply_declarations(runtime, manifest, handle.declarations, handle=handle)
                    loaded.append(handle)
                elif manifest.isolation is IsolationMode.INPROCESS:
                    if not self.allow_inprocess:
                        logger.error(
                            "refusing inprocess plugin %s (set SHEA_ALLOW_INPROCESS_PLUGINS=1)",
                            manifest.id,
                        )
                        continue
                    self._load_inprocess(runtime, entry, manifest)
                    loaded.append(manifest)
                else:
                    logger.error("unknown isolation for %s", manifest.id)
            except Exception as exc:
                logger.error("failed to load extension %s: %s", manifest.id, exc)

        return loaded

    def _load_inprocess(self, runtime: SheaRuntime, path: Path, manifest: Any) -> None:
        # Existing importlib path — TRUSTED/CORE only, env-gated.
        import importlib.util
        import sys

        init = path / "__init__.py"
        mod_name = f"shea_plugin_{manifest.id.replace('.', '_')}"
        spec = importlib.util.spec_from_file_location(mod_name, init)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        # find registerable plugin...
        proxy = RestrictedRuntimeProxy(
            runtime,
            manifest.name,
            {"permissions": sorted(manifest.permissions)},
        )
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and hasattr(attr, "register") and hasattr(attr, "name"):
                if attr.__name__ == "SheaPlugin":
                    continue
                attr().register(proxy)

    def shutdown(self) -> None:
        for h in self._handles:
            h.close()
        self._handles.clear()