from __future__ import annotations

import hashlib
import json
from typing import Any


class IdempotencyKeyGenerator:
    """Creates deterministic keys for logically identical operations."""

    @staticmethod
    def generate(
        *,
        task_id: str,
        tool: str,
        action: str,
        arguments: dict[str, Any],
    ) -> str:
        payload = json.dumps(
            {
                "task_id": task_id,
                "tool": tool,
                "action": action,
                "arguments": arguments,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

        return hashlib.sha256(payload.encode("utf-8")).hexdigest()