from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EnvironmentSnapshot:
    """Authorized session/environment probe — no side effects."""

    platform: str
    system: str
    release: str
    python_version: str
    pid: int
    uid: int | None
    cwd: str
    captured_at: datetime
    headless: bool
    notes: tuple[str, ...] = ()


def probe_environment(*, clock_now: datetime) -> EnvironmentSnapshot:
    uid: int | None
    try:
        uid = os.getuid()
    except AttributeError:
        uid = None

    notes: list[str] = []
    if sys.platform.startswith("linux"):
        notes.append("linux")
    elif sys.platform == "darwin":
        notes.append("macos")
    elif sys.platform == "win32":
        notes.append("windows")

    return EnvironmentSnapshot(
        platform=sys.platform,
        system=platform.system(),
        release=platform.release(),
        python_version=platform.python_version(),
        pid=os.getpid(),
        uid=uid,
        cwd=os.getcwd(),
        captured_at=clock_now,
        headless=not bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
        notes=tuple(notes),
    )