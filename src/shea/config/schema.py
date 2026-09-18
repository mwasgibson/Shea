from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Basic expected types for known configuration keys.
# Unknown keys will be allowed (for future extensibility) but logged.
# If a key exists here, its type MUST match, or it will be discarded
# to prevent type-confusion attacks at the config level.
EXPECTED_SCHEMA: dict[str, type | tuple[type, ...]] = {
    "_version": int,
    "allow_unsigned_plugins": bool,
    "sandbox_required": bool,
    "external_content_can_authorize": bool,
    "max_tool_privilege_level": str,
    # Add other known keys as needed
}


def validate_config(data: dict[str, Any]) -> dict[str, Any]:
    """Validate a loaded configuration dictionary against the schema.
    
    Drops keys with invalid types and logs a warning.
    """
    validated: dict[str, Any] = {}
    for k, v in data.items():
        if k in EXPECTED_SCHEMA:
            expected_type = EXPECTED_SCHEMA[k]
            if not isinstance(v, expected_type):
                logger.warning(
                    "Invalid type for config key %r: expected %s, got %s. Ignored.",
                    k,
                    expected_type.__name__ if isinstance(expected_type, type) else "tuple",
                    type(v).__name__,
                )
                continue
        validated[k] = v
    return validated