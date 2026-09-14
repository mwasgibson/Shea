from __future__ import annotations

from typing import Protocol

from shea.app.contracts import AdapterResult, ExecutionContract
from shea.app.ports.process import AdapterContext


class ApplicationControlPort(Protocol):
    """EP § application control — discover/launch/activate/terminate."""

    name: str

    def launch(self, contract: ExecutionContract, ctx: AdapterContext) -> AdapterResult: ...
    def activate(self, contract: ExecutionContract, ctx: AdapterContext) -> AdapterResult: ...
    def terminate(self, contract: ExecutionContract, ctx: AdapterContext) -> AdapterResult: ...
    def inspect(self, contract: ExecutionContract, ctx: AdapterContext) -> AdapterResult: ...