from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from shea.contracts.models import ToolRequest, ToolResponse

# Duplicated from shea.tools.registry.ToolHandler rather than imported,
# so this port stays dependency-free like every other file in shea.ports
# — ports must not depend on the packages that implement them.
BoundaryHandler = Callable[[ToolRequest], ToolResponse]


@dataclass(frozen=True)
class IsolationLimits:
    """OS-level isolation knobs for a single invocation.

    These are mechanical constraints applied *around* the handler/process.
    They do not replace capability checks, path policy, or network policy.
    """

    require_new_session: bool = True
    """Unix: start a new session (setsid) so the child is process-group leader."""

    memory_bytes: int | None = 512 * 1024 * 1024
    """RLIMIT_AS soft/hard cap in the child (Unix). None = do not set."""

    cpu_seconds: int | None = 30
    """RLIMIT_CPU in the child (Unix). None = do not set."""

    max_open_files: int | None = 256
    """RLIMIT_NOFILE in the child (Unix). None = do not set."""

    max_processes: int | None = 64
    """RLIMIT_NPROC in the child (Unix). None = do not set."""

    forbid_core_dumps: bool = True
    """RLIMIT_CORE = 0 in the child."""

    drop_capabilities_best_effort: bool = False
    """Reserved for future prctl/NO_NEW_PRIVS; V1 is best-effort only."""


@dataclass(frozen=True)
class ExecutionScope:
    """Sandbox parameters for one tool call (resource + OS isolation).

    Filesystem/network *policy* stays in SecurityService — not duplicated here.
    """

    max_runtime_seconds: float | None = 30.0
    redact_secrets: bool = True
    max_output_bytes: int | None = 1_000_000
    isolation: IsolationLimits = field(default_factory=IsolationLimits)


class ExecutionBoundary(Protocol):
    """Resource boundary stage — timeout, redaction, output caps.

    OS process isolation for *spawned* work lives in adapters via
    ``shea.security.isolation``. This protocol is the in-process
    resource wrapper around tool handlers.
    """

    def run(
        self, request: ToolRequest, handler: BoundaryHandler, scope: ExecutionScope
    ) -> ToolResponse: ...