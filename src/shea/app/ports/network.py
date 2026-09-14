from __future__ import annotations

from typing import Protocol

from shea.app.contracts import AdapterResult, ExecutionContract
from shea.app.ports.process import AdapterContext


class NetworkControlPort(Protocol):
    """EP network operations under NetworkScope + destination checks."""

    name: str

    def request(self, contract: ExecutionContract, ctx: AdapterContext) -> AdapterResult: ...