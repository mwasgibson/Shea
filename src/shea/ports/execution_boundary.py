from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from shea.contracts.models import ToolRequest, ToolResponse

# Duplicated from shea.tools.registry.ToolHandler rather than imported,
# so this port stays dependency-free like every other file in shea.ports
# — ports must not depend on the packages that implement them.
BoundaryHandler = Callable[[ToolRequest], ToolResponse]


@dataclass(frozen=True)
class ExecutionScope:
    """Mechanical sandboxing parameters for a single tool call.

    Deliberately does NOT carry filesystem/network policy — that's
    shea.security.FilesystemPolicy/NetworkPolicy's job, enforced once by
    SecurityService before a request ever reaches a boundary, not
    duplicated here. This scope covers only what a boundary implementation
    itself is responsible for: how long to allow the call to run, and
    whether to redact its output.
    """

    max_runtime_seconds: float | None = None
    redact_secrets: bool = True


class ExecutionBoundary(Protocol):
    """Runtime isolation boundary for tool execution — the "Sandbox" stage
    in the pipeline research doc Section 16.4 describes as
    "Authorized Plan -> Capability Check -> Sandbox -> Tool -> OS".

    Receives an already-resolved handler, not a registry: a boundary's
    job is to run *this specific call* under constraints, not to look
    anything up. That keeps exactly one code path in ToolExecutor that
    can invoke a handler, ever.
    """

    def run(
        self, request: ToolRequest, handler: BoundaryHandler, scope: ExecutionScope
    ) -> ToolResponse: ...