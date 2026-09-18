from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from shea.bootstrap import SheaRuntime
from shea.extensions.plugin import SheaPlugin
from shea.extensions.security import RestrictedRuntimeProxy

logger = logging.getLogger(__name__)


class PluginLoader:
    """Discovers and loads third-party plugins into the runtime."""

    def __init__(self, plugin_dir: str = "plugins") -> None:
        self.plugin_dir = Path(plugin_dir)

    def load_plugins(self, runtime: SheaRuntime) -> list[SheaPlugin]:
        loaded: list[SheaPlugin] = []
        if not self.plugin_dir.exists() or not self.plugin_dir.is_dir():
            return loaded

        # Add plugins dir to path so plugins can import each other if needed
        if str(self.plugin_dir.absolute()) not in sys.path:
            sys.path.insert(0, str(self.plugin_dir.absolute()))

        for entry in os.listdir(self.plugin_dir):
            path = self.plugin_dir / entry
            
            # Look for python modules (.py files or directories with __init__.py)
            mod_name = None
            if path.is_file() and path.suffix == ".py" and path.stem != "__init__":
                mod_name = path.stem
            elif path.is_dir() and (path / "__init__.py").exists():
                mod_name = path.name

            if not mod_name:
                continue

            try:
                spec = importlib.util.spec_from_file_location(
                    mod_name, path if path.is_file() else path / "__init__.py"
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[mod_name] = module
                    spec.loader.exec_module(module)
                    
                    # Look for classes implementing SheaPlugin by convention.
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if isinstance(attr, type) and hasattr(
                            attr, "register") and hasattr(attr, "name"):
                            # Skip the Protocol itself
                            if attr.__name__ == "SheaPlugin":
                                continue
                            
                            plugin_instance = cast(SheaPlugin, attr())
                            
                            # Manifest enforcement
                            manifest_path = (path if path.is_dir() else path.parent) / "manifest.json"
                            manifest_data: dict[str, Any] = {}
                            if manifest_path.exists():
                                try:
                                    with open(manifest_path) as mf:
                                        manifest_data = cast('dict[str, Any]', json.load(mf))
                                except Exception as me:
                                    logger.error(f"Failed to read manifest for {plugin_instance.name}: {me}")
                            else:
                                logger.warning(f"Plugin {plugin_instance.name} has no manifest.json! Operating with zero permissions.")
                                
                            proxy = RestrictedRuntimeProxy(runtime, plugin_instance.name, manifest_data)
                            
                            # We pass the proxy instead of the real runtime!
                            plugin_instance.register(proxy)  # type: ignore[arg-type]
                            loaded.append(plugin_instance)
                            logger.info(f"Successfully loaded plugin: {plugin_instance.name}")
            except Exception as e:
                logger.error(f"Failed to load plugin {mod_name}: {e}")

        return loaded

