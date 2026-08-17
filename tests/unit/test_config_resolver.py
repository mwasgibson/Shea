from __future__ import annotations

from shea.config.layers import ConfigLayer
from shea.config.resolver import ConfigResolver


def test_most_specific_layer_wins_for_ordinary_keys() -> None:
    resolver = ConfigResolver()
    resolver.set_layer_value(ConfigLayer.SYSTEM, "log_level", "INFO")
    resolver.set_layer_value(ConfigLayer.USER, "log_level", "DEBUG")

    assert resolver.resolve("log_level") == "DEBUG"


def test_missing_key_returns_default() -> None:
    resolver = ConfigResolver()
    assert resolver.resolve("nonexistent", default="fallback") == "fallback"


def test_security_invariant_key_ignores_lower_layers() -> None:
    """Research doc Section 13.3's exact worked example:
    System: allow_unsigned_plugins = false
    Project: allow_unsigned_plugins = true
    Effective: false
    """
    resolver = ConfigResolver()
    resolver.set_layer_value(ConfigLayer.SYSTEM, "allow_unsigned_plugins", False)
    resolver.set_layer_value(ConfigLayer.PROJECT, "allow_unsigned_plugins", True)
    resolver.set_layer_value(ConfigLayer.SESSION, "allow_unsigned_plugins", True)

    assert resolver.resolve("allow_unsigned_plugins") is False


def test_security_invariant_key_with_no_system_value_uses_default() -> None:
    resolver = ConfigResolver()
    resolver.set_layer_value(ConfigLayer.PROJECT, "sandbox_required", False)

    assert resolver.resolve("sandbox_required", default=True) is True


def test_effective_config_merges_layers_with_precedence() -> None:
    resolver = ConfigResolver()
    resolver.set_layer_value(ConfigLayer.SYSTEM, "a", 1)
    resolver.set_layer_value(ConfigLayer.SYSTEM, "b", 1)
    resolver.set_layer_value(ConfigLayer.USER, "b", 2)
    resolver.set_layer_value(ConfigLayer.SESSION, "c", 3)

    effective = resolver.effective_config()

    assert effective["a"] == 1
    assert effective["b"] == 2
    assert effective["c"] == 3


def test_effective_config_forces_invariant_keys_to_system_value() -> None:
    resolver = ConfigResolver()
    resolver.set_layer_value(ConfigLayer.SYSTEM, "allow_unsigned_plugins", False)
    resolver.set_layer_value(ConfigLayer.SESSION, "allow_unsigned_plugins", True)

    effective = resolver.effective_config()

    assert effective["allow_unsigned_plugins"] is False


def test_effective_config_omits_invariant_key_absent_from_system() -> None:
    resolver = ConfigResolver()
    resolver.set_layer_value(ConfigLayer.PROJECT, "sandbox_required", True)

    effective = resolver.effective_config()

    assert "sandbox_required" not in effective
