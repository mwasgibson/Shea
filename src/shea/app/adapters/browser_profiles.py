from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shea.app.scopes import BrowserProfileMode, BrowserScope
from shea.security.exceptions import SecurityViolationError


@dataclass(frozen=True)
class BrowserLaunchPlan:
    mode: BrowserProfileMode
    user_data_dir: str | None
    ephemeral: bool
    storage_state: None = None  # always None in EPHEMERAL


def plan_browser_launch(scope: BrowserScope, *, workspace: Path | None = None) -> BrowserLaunchPlan:
    mode = scope.profile_mode

    if mode is BrowserProfileMode.EPHEMERAL_ISOLATED:
        return BrowserLaunchPlan(mode=mode, user_data_dir=None, ephemeral=True)

    if mode is BrowserProfileMode.ATTACH_EXISTING_SESSION:
        if not scope.allow_attach_cdp:
            raise SecurityViolationError(
                "browser",
                "profile",
                "ATTACH_EXISTING_SESSION denied (allow_attach_cdp=False)",
            )
        raise SecurityViolationError(
            "browser",
            "profile",
            "ATTACH_EXISTING_SESSION requires explicit CDP endpoint in arguments "
            "and is disabled by default for security",
        )

    if mode in {
        BrowserProfileMode.PERSISTENT_SHEA_PROFILE,
        BrowserProfileMode.USER_APPROVED_EXISTING_PROFILE,
    }:
        if not scope.allowed_profile_dirs:
            raise SecurityViolationError(
                "browser",
                "profile",
                f"{mode.value} requires non-empty allowed_profile_dirs",
            )
        # Caller must pass profile_dir in arguments; must be under allowlist
        return BrowserLaunchPlan(mode=mode, user_data_dir=None, ephemeral=False)

    raise SecurityViolationError("browser", "profile", f"unknown mode {mode!r}")


def assert_profile_dir_allowed(profile_dir: str, scope: BrowserScope) -> Path:
    real = Path(profile_dir).resolve()
    for allowed in scope.allowed_profile_dirs:
        root = Path(allowed).resolve()
        try:
            real.relative_to(root)
            return real
        except ValueError:
            continue
    raise SecurityViolationError(
        "browser",
        "profile",
        f"profile dir {str(real)!r} not under allowed_profile_dirs",
    )