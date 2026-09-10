from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from shea.app.contracts import AdapterResult, ExecutionContract
from shea.app.identities import VerifiedIdentity
from shea.app.scopes import ExecutionScope, ScopeEnforcementReport


@dataclass(frozen=True)
class AdapterContext:
    verified_identity: VerifiedIdentity
    scope: ExecutionScope
    enforcement: ScopeEnforcementReport
    environ_allowlist: dict[str, str] = field(default_factory=dict[str, str])


class ProcessControlPort(Protocol):
    """EP §8 process control — controlled argv/env/I/O, cancellation, evidence."""

    name: str

    def spawn(
        self,
        contract: ExecutionContract,
        ctx: AdapterContext,
        *,
        argv: list[str],
        stdin_data: bytes | None = None,
    ) -> AdapterResult: ...