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
class ExecutionScope:
    scope_id: str
    filesystem: FilesystemScope = field(default_factory=FilesystemScope)
    network: NetworkScope = field(default_factory=NetworkScope)
    process: ProcessScope = field(default_factory=ProcessScope)
    resources: ResourceLimits = field(default_factory=ResourceLimits)
    isolation: IsolationPolicy = field(default_factory=IsolationPolicy)


@dataclass(frozen=True)
class ScopeEnforcementReport:
    """Per-limit enforcement result — required UNSUPPORTED fails closed."""

    scope_id: str
    limits: dict[str, EnforcementStatus]
    isolation: dict[str, EnforcementStatus]
    filesystem: dict[str, EnforcementStatus]
    acceptable: bool
    detail: str = ""