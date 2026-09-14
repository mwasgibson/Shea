from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionPermit:
    """Process-local proof that agent gates already ran for this invocation.

    Not a capability grant across processes. Aligns with
    MODEL ≠ AUTHORITY: the model cannot mint this; only ExecutionService does.
    """

    token: str
    tool: str
    action: str
    arguments_digest: str
    capabilities_digest: str


class ExecutionPermitAuthority:
    """Mints and verifies permits with a process-lifetime secret."""

    def __init__(self, secret: bytes | None = None) -> None:
        self._secret = secret or secrets.token_bytes(32)

    @staticmethod
    def _digest_args(arguments: Mapping[str, Any]) -> str:
        payload = json.dumps(arguments, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _digest_caps(capabilities: frozenset[str]) -> str:
        return hashlib.sha256(
            "\0".join(sorted(capabilities)).encode()
        ).hexdigest()

    def mint(
        self,
        *,
        tool: str,
        action: str,
        arguments: Mapping[str, Any],
        capabilities: frozenset[str],
    ) -> ExecutionPermit:
        args_d = self._digest_args(arguments)
        caps_d = self._digest_caps(capabilities)
        msg = f"{tool}\0{action}\0{args_d}\0{caps_d}".encode()
        token = hmac.new(self._secret, msg, hashlib.sha256).hexdigest()
        return ExecutionPermit(
            token=token,
            tool=tool,
            action=action,
            arguments_digest=args_d,
            capabilities_digest=caps_d,
        )

    def verify(
        self,
        permit: ExecutionPermit,
        *,
        tool: str,
        action: str,
        arguments: Mapping[str, Any],
        capabilities: frozenset[str],
    ) -> bool:
        expected = self.mint(
            tool=tool,
            action=action,
            arguments=arguments,
            capabilities=capabilities,
        )
        return hmac.compare_digest(permit.token, expected.token)