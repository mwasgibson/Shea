from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, cast

REDACTED = "[REDACTED]"

# Research doc Section 11.7's example secret shapes. Pattern-based
# detection is inherently heuristic — it catches recognizable shapes
# (AWS-style access keys, bearer tokens, a common "sk-" API key prefix,
# generic key=value pairs) but cannot catch every possible secret
# format. This is defense in depth, not the primary control: Section
# 11.7 is explicit that secrets belong in a dedicated secret store, not
# general context, in the first place.
DEFAULT_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{10,}"),
    re.compile(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*\S+"),
)


@dataclass(frozen=True)
class SecretRedactor:
    """Structurally satisfies shea.ports.redactor.Redactor. Recursively
    walks a metadata mapping, redacting matched substrings out of every
    string value (including inside nested dicts/lists), so a secret
    embedded anywhere in a tool argument or audit metadata payload is
    caught, not just top-level values.
    """

    patterns: tuple[re.Pattern[str], ...] = field(
        default_factory=lambda: DEFAULT_SECRET_PATTERNS
    )

    def redact(self, value: str) -> str:
        redacted = value
        for pattern in self.patterns:
            redacted = pattern.sub(REDACTED, redacted)
        return redacted

    def redact_mapping(self, data: dict[str, Any]) -> dict[str, Any]:
        return {key: self._redact_value(value) for key, value in data.items()}

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            typed_dict = cast(dict[str, Any], value)
            return self.redact_mapping(typed_dict)
        if isinstance(value, list):
            items = cast(list[object], value)
            return [self._redact_value(item) for item in items]
        return value