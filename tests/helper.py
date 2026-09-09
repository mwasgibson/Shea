from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MINIMAL_SCHEMA: dict[str, Mapping[str, Any]] = {
    "_unused": {"type": "any", "required": False, "default": None},
}