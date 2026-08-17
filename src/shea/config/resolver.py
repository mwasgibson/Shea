from __future__ import annotations

from dataclasses import dataclass, field
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