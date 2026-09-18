from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .invariants import DEFAULT_SECURITY_INVARIANT_KEYS
from .layers import LAYER_PRECEDENCE, ConfigLayer

_UNSET = object()

def _empty_layers() -> dict[ConfigLayer, dict[str, Any]]:
    return {}

@dataclass
class ConfigResolver:
    """Resolves effective configuration across the six layers.

    Two lookup rules, applied per key:

    1. If the key is a security invariant, only the SYSTEM layer's value
       is ever consulted — Machine/User/Profile/Project/Session values for
       that key are inert, on purpose, per research doc Section 13.3.
    2. Otherwise, the most specific layer that defines the key wins,
       walking Session -> Project -> Profile -> User -> Machine -> System.
    """

    layers: dict[ConfigLayer, dict[str, Any]] = field(default_factory=_empty_layers)
    security_invariant_keys: frozenset[str] = DEFAULT_SECURITY_INVARIANT_KEYS

    def resolve(self, key: str, default: Any = None) -> Any:
        if key in self.security_invariant_keys:
            system_values = self.layers.get(ConfigLayer.SYSTEM, {})
            return system_values.get(key, default)

        for layer in LAYER_PRECEDENCE:
            layer_values = self.layers.get(layer, {})
            value = layer_values.get(key, _UNSET)
            if value is not _UNSET:
                return value
        return default

    def effective_config(self) -> dict[str, Any]:
        """Materialize the full effective configuration as a flat dict.

        Built by applying layers System-first, most-specific-last (so
        later `update()` calls override earlier ones) — then invariant
        keys are forced back to their SYSTEM value regardless of what any
        later layer wrote.
        """
        result: dict[str, Any] = {}
        for layer in reversed(LAYER_PRECEDENCE):  # SYSTEM ... SESSION
            result.update(self.layers.get(layer, {}))

        system_values = self.layers.get(ConfigLayer.SYSTEM, {})
        for key in self.security_invariant_keys:
            if key in system_values:
                result[key] = system_values[key]
            else:
                result.pop(key, None)

        return result

    def set_layer_value(self, layer: ConfigLayer, key: str, value: Any) -> None:
        self.layers.setdefault(layer, {})[key] = value
def build_default_resolver() -> ConfigResolver:
    import logging

    from shea.config.schema import validate_config
    from shea.config.trust import ProjectTrustManager
    
    logger = logging.getLogger(__name__)
    resolver = ConfigResolver()
    
    # Machine layer (e.g., /etc/shea/config.json)
    machine_path = Path("/etc/shea/config.json")
    if machine_path.is_file():
        try:
            with open(machine_path) as f:
                resolver.layers[ConfigLayer.MACHINE] = validate_config(json.load(f))
        except Exception as e:
            logger.warning("Failed to load machine config: %s", e)
            
    # User layer (e.g., ~/.shea/config.json)
    user_path = Path.home() / ".shea" / "config.json"
    if user_path.is_file():
        try:
            with open(user_path) as f:
                resolver.layers[ConfigLayer.USER] = validate_config(json.load(f))
        except Exception as e:
            logger.warning("Failed to load user config: %s", e)

    # Project layer (cwd / .shea/config.json)
    project_path = Path.cwd() / ".shea" / "config.json"
    if project_path.is_file():
        trust_manager = ProjectTrustManager()
        if trust_manager.is_trusted(Path.cwd()):
            try:
                with open(project_path) as f:
                    resolver.layers[ConfigLayer.PROJECT] = validate_config(json.load(f))
            except Exception as e:
                logger.warning("Failed to load project config: %s", e)
        else:
            logger.warning(
                "Skipping project config %s because the project is not trusted. "
                "Add it to ~/.shea/trusted_projects.json to enable it.",
                project_path
            )
            
    # Environment layer
    env_config = {}
    for k, v in os.environ.items():
        if k.startswith("SHEA_"):
            env_config[k] = v
    if env_config:
        resolver.layers[ConfigLayer.SESSION] = env_config  # Env vars are always strings, let them pass loosely
        
    return resolver