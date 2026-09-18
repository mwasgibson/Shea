from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shea.ports.execution_boundary import IsolationLimits


@dataclass(frozen=True)
class IsolationPlan:
    """What will actually be applied on this platform."""

    platform: str
    new_session: bool
    rlimits: dict[str, tuple[int, int]]
    notes: tuple[str, ...] = ()


def plan_isolation(limits: IsolationLimits) -> IsolationPlan:
    """Describe isolation for the current OS without applying it."""
    platform = sys.platform
    notes: list[str] = []
    rlimits: dict[str, tuple[int, int]] = {}

    if platform.startswith("win"):
        notes.append("windows: setsid/rlimit not applied; job-object isolation is future work")
        return IsolationPlan(
            platform=platform,
            new_session=False,
            rlimits={},
            notes=tuple(notes),
        )

    if limits.memory_bytes is not None:
        rlimits["AS"] = (limits.memory_bytes, limits.memory_bytes)
    if limits.cpu_seconds is not None:
        rlimits["CPU"] = (limits.cpu_seconds, limits.cpu_seconds)
    if limits.max_open_files is not None:
        rlimits["NOFILE"] = (limits.max_open_files, limits.max_open_files)
    if limits.max_processes is not None:
        rlimits["NPROC"] = (limits.max_processes, limits.max_processes)
    if limits.forbid_core_dumps:
        rlimits["CORE"] = (0, 0)

    if limits.drop_capabilities_best_effort:
        notes.append("NO_NEW_PRIVS requested (best-effort; may be unavailable)")

    return IsolationPlan(
        platform=platform,
        new_session=bool(limits.require_new_session),
        rlimits=rlimits,
        notes=tuple(notes),
    )


def _resource_const(name: str) -> int | None:
    try:
        import resource
    except ImportError:
        return None
    return getattr(resource, f"RLIMIT_{name}", None)


def apply_rlimits(rlimits: dict[str, tuple[int, int]]) -> dict[str, str]:
    """Apply RLIMIT_* in the *current* process (intended for child preexec)."""
    applied: dict[str, str] = {}
    try:
        import resource
    except ImportError:
        return {"error": "resource module unavailable"}

    for name, (soft, hard) in rlimits.items():
        const = _resource_const(name)
        if const is None:
            applied[name] = "unsupported"
            continue
        try:
            resource.setrlimit(const, (soft, hard))
            applied[name] = f"{soft}:{hard}"
        except (ValueError, OSError) as exc:
            applied[name] = f"failed:{exc}"
    return applied


def try_no_new_privs() -> bool:
    """Best-effort Linux NO_NEW_PRIVS via prctl. Returns True if set."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes

        # PR_SET_NO_NEW_PRIVS = 38
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        rc = libc.prctl(38, 1, 0, 0, 0)
        return rc == 0
    except Exception:
        return False


def make_preexec_fn(limits: IsolationLimits) -> Callable[[], None] | None:
    """Build a subprocess preexec_fn for Unix child isolation.

    Returns None on Windows (caller must not pass preexec_fn).
    """
    if sys.platform.startswith("win"):
        return None

    plan = plan_isolation(limits)
    want_nnp = limits.drop_capabilities_best_effort

    def _preexec() -> None:
        # New session first so rlimits apply to the session leader.
        if plan.new_session:
            os.setsid()
        apply_rlimits(plan.rlimits)
        if want_nnp:
            try_no_new_privs()

    return _preexec


def isolation_metadata(limits: IsolationLimits) -> dict[str, Any]:
    plan = plan_isolation(limits)
    return {
        "platform": plan.platform,
        "new_session": plan.new_session,
        "rlimits": {k: list(v) for k, v in plan.rlimits.items()},
        "notes": list(plan.notes),
    }



def wrap_command_for_isolation(cmd: list[str], allowed_write_dir: Path | None = None) -> list[str]:
    platform = sys.platform
    
    if platform == "darwin" and allowed_write_dir:
        profile = (
            "(version 1)\n"
            "(allow default)\n"
            "(deny network*)\n"
            "(deny file-write*)\n"
            f"(allow file-write* (subpath \"{allowed_write_dir.resolve()}\"))\n"
            "(allow network* (remote unix-socket))"
        )
        return ["sandbox-exec", "-p", profile] + cmd
        
    if platform.startswith("linux") and allowed_write_dir:
        if shutil.which("bwrap"):
            return [
                "bwrap",
                "--ro-bind", "/", "/",
                "--dev", "/dev",
                "--bind", str(allowed_write_dir.resolve()), str(allowed_write_dir.resolve()),
                "--unshare-net"
            ] + cmd
            
    return cmd