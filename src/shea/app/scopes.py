from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum


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
    # SPKI pin: SHA-256 of the peer cert SPKI, base64 or hex (lowercase).
    # Empty = no pin (still require normal TLS verify).
    pinned_spki_sha256: frozenset[str] = frozenset()
    # Proxy: None = direct only; set only when allow_proxy is True.
    allow_proxy: bool = False
    proxy_url: str | None = None
    # Per-destination credential refs: hostname -> credential id (never secret).
    destination_credentials: dict[str, str] = field(default_factory=dict[str, str])


class BrowserProfileMode(StrEnum):
    EPHEMERAL_ISOLATED = "EPHEMERAL_ISOLATED"
    PERSISTENT_SHEA_PROFILE = "PERSISTENT_SHEA_PROFILE"
    USER_APPROVED_EXISTING_PROFILE = "USER_APPROVED_EXISTING_PROFILE"
    ATTACH_EXISTING_SESSION = "ATTACH_EXISTING_SESSION"


@dataclass(frozen=True)
class BrowserScope:
    """Browser security boundary — cookies/storage/profile isolation."""

    profile_mode: BrowserProfileMode = BrowserProfileMode.EPHEMERAL_ISOLATED
    """Default EPHEMERAL: no durable cookies; fresh context per invoke."""
    allowed_profile_dirs: frozenset[str] = frozenset()
    """Only used for PERSISTENT_SHEA_PROFILE / USER_APPROVED paths."""
    allow_downloads: bool = False
    allow_uploads: bool = False
    allow_attach_cdp: bool = False
    """ATTACH_EXISTING_SESSION requires this True + explicit CDP endpoint."""
    content_trust: str = "DATA"
    """Always DATA — page content never becomes AUTHORITY."""


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
class IsolationLimits:
    require_new_session: bool = False
    memory_bytes: int | None = None
    cpu_seconds: int = 30
    max_open_files: int = 256
    max_processes: int = 64
    forbid_core_dumps: bool = True


def to_port_isolation(scope: ExecutionScope) -> IsolationLimits:
    iso = scope.isolation
    res = scope.resources
    return IsolationLimits(
        require_new_session=bool(iso.require_new_session),
        memory_bytes=res.memory_bytes,
        cpu_seconds=int(res.wall_time_ms / 1000) if res.wall_time_ms else 30,
        max_open_files=getattr(res, "max_open_files", 256),
        max_processes=getattr(res, "max_processes", 64),
        forbid_core_dumps=True,
    )

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
    browser: BrowserScope = field(default_factory=BrowserScope)
    resources: ResourceLimits = field(default_factory=ResourceLimits)
    isolation: IsolationPolicy = field(default_factory=IsolationPolicy)


@dataclass(frozen=True)
class ScopeEnforcementReport:
    """Per-limit enforcement result — required UNSUPPORTED fails closed."""

    scope_id: str
    limits: dict[str, EnforcementStatus]
    isolation: dict[str, EnforcementStatus]
    filesystem: dict[str, EnforcementStatus]
    process: dict[str, EnforcementStatus] = field(default_factory=dict[str, EnforcementStatus])
    network: dict[str, EnforcementStatus] = field(default_factory=dict[str, EnforcementStatus])
    application: dict[str, EnforcementStatus] = field(default_factory=dict[str, EnforcementStatus])
    browser: dict[str, EnforcementStatus] = field(default_factory=dict[str, EnforcementStatus])
    acceptable: bool = True
    detail: str = ""