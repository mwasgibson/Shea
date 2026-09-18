from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ProjectTrustManager:
    """Manages project trust boundaries.
    
    A local project's `.shea/config.json` should not be loaded unless the user
    has explicitly trusted that project path. This prevents malicious downloads
    from silently overriding secure settings via a local config file.
    """
    
    def __init__(self, storage_path: Path | None = None) -> None:
        if storage_path is None:
            storage_path = Path.home() / ".shea" / "trusted_projects.json"
        self.storage_path = storage_path

    def _load(self) -> set[str]:
        if not self.storage_path.is_file():
            return set()
        try:
            with open(self.storage_path) as f:
                data = json.load(f)
                paths: Path = data.get("trusted_paths", [])
                if isinstance(paths, list):
                    return set(paths)
                return set()
        except Exception as e:
            logger.warning("Failed to load trusted projects from %s: %s", self.storage_path, e)
            return set()

    def _save(self, trusted: set[str]) -> None:
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, "w") as f:
                json.dump({"trusted_paths": sorted(list(trusted))}, f, indent=2)
        except Exception as e:
            logger.error("Failed to save trusted projects to %s: %s", self.storage_path, e)

    def is_trusted(self, path: Path) -> bool:
        """Check if a project path is trusted."""
        trusted = self._load()
        return str(path.resolve()) in trusted

    def trust_project(self, path: Path) -> None:
        """Mark a project path as trusted."""
        trusted = self._load()
        resolved = str(path.resolve())
        if resolved not in trusted:
            trusted.add(resolved)
            self._save(trusted)
            logger.info("Project path %s is now trusted.", resolved)

    def untrust_project(self, path: Path) -> None:
        """Remove a project path from the trusted list."""
        trusted = self._load()
        resolved = str(path.resolve())
        if resolved in trusted:
            trusted.remove(resolved)
            self._save(trusted)
            logger.info("Project path %s is no longer trusted.", resolved)