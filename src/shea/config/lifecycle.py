from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CURRENT_CONFIG_VERSION = 1


def backup_config(path: Path) -> Path | None:
    """Create a backup of the configuration file before modification.
    
    Returns the Path to the backup file, or None if the original doesn't exist.
    """
    if not path.is_file():
        return None
    
    backup_path = path.with_suffix(f".json.bak.{int(time.time())}")
    try:
        shutil.copy2(path, backup_path)
        logger.info("Backed up config %s to %s", path, backup_path)
        return backup_path
    except OSError as e:
        logger.warning("Failed to backup config %s: %s", path, e)
        return None


def restore_config(target: Path, backup: Path) -> bool:
    """Restore a configuration file from a backup."""
    if not backup.is_file():
        logger.error("Backup file %s does not exist", backup)
        return False
        
    try:
        shutil.copy2(backup, target)
        logger.info("Restored config %s from %s", target, backup)
        return True
    except OSError as e:
        logger.error("Failed to restore config %s from %s: %s", target, backup, e)
        return False


def migrate_config(data: dict[str, Any], to_version: int = CURRENT_CONFIG_VERSION) -> dict[str, Any]:
    """Apply migrations to a configuration dictionary to bring it to `to_version`."""
    current = data.get("_version", 1)
    
    if current > to_version:
        logger.warning("Config version %d is newer than target version %d", current, to_version)
        return data
        
    # Example migration (uncomment when we have v2)
    # if current == 1 and to_version >= 2:
    #     # Do v1 -> v2 migration
    #     current = 2
        
    data["_version"] = to_version
    return data


def safe_save_config(path: Path, data: dict[str, Any]) -> None:
    """Safely save a configuration dictionary to a file, migrating and backing up first."""
    data = migrate_config(data)
    backup_config(path)
    
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".json.tmp")
    
    try:
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=2)
        temp_path.replace(path)
    except Exception as e:
        logger.error("Failed to save config to %s: %s", path, e)
        if temp_path.exists():
            temp_path.unlink()
        raise