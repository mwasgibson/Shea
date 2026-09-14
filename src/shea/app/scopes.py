from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EnforcementStatus(Enum):
    ENFORCED = "ENFORCED"
    PARTIALLY_ENFORCED = "PARTIALLY_ENFORCED"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_REQUESTED = "NOT_REQUESTED"


@dataclass(frozen=True)
class FilesystemScope:
    allowed_roots: frozenset[str] = frozenset()
    read_only: bool = False
    write_only: bool =False


@dataclass(frozen=True)
class NetworkScope:
    allowed_hosts: frozenset[str] | None = None  # None = no network by default for process
    block_private: bool = True


@dataclass(frozen=True)
class ProcessScope:
    allowed_executables: frozenset[str] = frozenset()
    allow_shell: bool = False
    inherit_environ: bool = False
    max_argv_len: int = 64


@dataclass(frozen=True)
class ResourceLimits:
    wall_time_ms: int | None = 30_000
    memory_bytes: int | None = None
    output_bytes: int | None = 1_000_000
    process_count: int | None = 1


@dataclass(frozen=True)
class IsolationPolicy:
    require_new_session: bool = False
    require_cgroup: bool = False  # V1: report UNSUPPORTED if required
    

@dataclass(frozen=True)
class ApplicationScope:
    """Constraints for application.* adapters (Phase 6).
    Empty allowlists fail closed: no launch/terminate by path or desktop id.
    """

    allowed_executables: frozenset[str] = frozenset()
    """Basenames or absolute paths permitted for launch (Windows/Linux/macOS path mode)."""
    allowed_desktop_ids: frozenset[str] = frozenset()
    """Linux gtk-launch desktop ids (e.g. firefox.desktop or firefox)."""
    allowed_bundle_ids: frozenset[str] = frozenset()
    """macOS bundle identifiers for open -b."""
    allowed_app_names: frozenset[str] = frozenset()
    """macOS open -a names / display names."""
    allow_xdg_open: bool = False
    """Linux: permit xdg-open only when True (still subject to URL policy later)."""
    allow_terminate: bool = False
    """If False, application.terminate is refused even with a pid."""


@dataclass(frozen=True)
class ExecutionScope:
    scope_id: str
    filesystem: FilesystemScope = field(default_factory=FilesystemScope)
    network: NetworkScope = field(default_factory=NetworkScope)
    process: ProcessScope = field(default_factory=ProcessScope)
    application: ApplicationScope = field(default_factory=ApplicationScope)
    resources: ResourceLimits = field(default_factory=ResourceLimits)
    isolation: IsolationPolicy = field(default_factory=IsolationPolicy)


@dataclass(frozen=True)
class ScopeEnforcementReport:
    """Per-limit enforcement result — required UNSUPPORTED fails closed."""

    scope_id: str
    limits: dict[str, EnforcementStatus]
    isolation: dict[str, EnforcementStatus]
    filesystem: dict[str, EnforcementStatus]
    network: dict[str, EnforcementStatus] = field(default_factory=dict[str, EnforcementStatus])
    application: dict[str, EnforcementStatus] = field(default_factory=dict[str, EnforcementStatus])
    acceptable: bool = True
    detail: str = ""