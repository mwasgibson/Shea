from __future__ import annotations

from pathlib import Path

from shea.app.scopes import ApplicationScope


def executable_allowed(path_or_name: str, scope: ApplicationScope) -> bool:
    allowed = scope.allowed_executables
    if not allowed:
        return False
    name = Path(path_or_name).name
    resolved: str | None
    try:
        resolved = str(Path(path_or_name).resolve())
    except OSError:
        resolved = None
    if path_or_name in allowed or name in allowed:
        return True
    if resolved is not None and resolved in allowed:
        return True
    return False


def desktop_id_allowed(desktop_id: str, scope: ApplicationScope) -> bool:
    allowed = scope.allowed_desktop_ids
    if not allowed:
        return False
    bare = desktop_id.removesuffix(".desktop")
    return (
        desktop_id in allowed
        or bare in allowed
        or f"{bare}.desktop" in allowed
    )


def bundle_id_allowed(bundle_id: str, scope: ApplicationScope) -> bool:
    return bool(scope.allowed_bundle_ids) and bundle_id in scope.allowed_bundle_ids


def app_name_allowed(name: str, scope: ApplicationScope) -> bool:
    return bool(scope.allowed_app_names) and name in scope.allowed_app_names