from __future__ import annotations

from typing import Any, Protocol


class Redactor(Protocol):
    """Abstraction over "strip secrets out of this metadata before it's
    persisted." Defined here, not imported concretely from shea.security,
    so shea.audit (used by every later phase) never depends on
    shea.security — which itself depends on shea.audit for AuditRecorder.
    A concrete implementation (shea.security.secrets.SecretRedactor)
    satisfies this structurally, no inheritance required.
    """

    def redact_mapping(self, data: dict[str, Any]) -> dict[str, Any]: ...