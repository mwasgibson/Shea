from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    channel: str
    requires_migration: bool
    changelog: str


class UpdateService:
    """Full update and rollback lifecycle system.
    
    Handles taking atomic snapshots of the system state (database, configurations),
    applying updates, running migrations, and rolling back if a failure occurs.
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.snapshots_dir = data_dir / "snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        
        # Key files that constitute the system state
        self.db_path = data_dir / "shea.db"
        self.env_path = data_dir / ".env"
        self.config_path = data_dir / "config.json"

    def check_for_updates(self, current_version: str, channel: str = "stable") -> UpdateManifest | None:
        """Query the release channel for available updates."""
        logger.info("Checking for updates on channel %s...", channel)
        # Stub: In a real system, this would query a release server or GitHub API.
        # Returning None implies no update available, but for demonstration we'll mock one.
        if current_version != "1.0.0-next":
            return UpdateManifest(
                version="1.0.0-next",
                channel=channel,
                requires_migration=True,
                changelog="* Added OperationGraph\n* Added Native Extension Isolation",
            )
        return None

    def create_snapshot(self, reason: str = "pre_update") -> Path:
        """Create a full point-in-time snapshot of system state."""
        timestamp = int(time.time())
        snapshot_id = f"snapshot_{timestamp}_{reason}"
        target_dir = self.snapshots_dir / snapshot_id
        target_dir.mkdir()

        # Safely copy critical state files if they exist
        if self.db_path.exists():
            # In a highly concurrent environment we'd use SQLite Online Backup API.
            # For this architecture, a file copy is a baseline.
            shutil.copy2(self.db_path, target_dir / "shea.db")
            
        if self.env_path.exists():
            shutil.copy2(self.env_path, target_dir / ".env")
            
        if self.config_path.exists():
            shutil.copy2(self.config_path, target_dir / "config.json")
            
        # Write metadata
        meta: dict[str, Any] = {
            "id": snapshot_id,
            "created_at": timestamp,
            "reason": reason,
        }
        with open(target_dir / "meta.json", "w") as f:
            json.dump(meta, f)
            
        logger.info(f"Created system snapshot: {snapshot_id}")
        return target_dir

    def rollback(self, snapshot_id: str) -> bool:
        """Restore the system entirely to a previous snapshot."""
        target_dir = self.snapshots_dir / snapshot_id
        if not target_dir.exists():
            logger.error(f"Snapshot {snapshot_id} does not exist.")
            return False
            
        logger.warning(f"INITIATING ROLLBACK TO SNAPSHOT: {snapshot_id}")
        try:
            if (target_dir / "shea.db").exists():
                shutil.copy2(target_dir / "shea.db", self.db_path)
            if (target_dir / ".env").exists():
                shutil.copy2(target_dir / ".env", self.env_path)
            if (target_dir / "config.json").exists():
                shutil.copy2(target_dir / "config.json", self.config_path)
                
            logger.info("Rollback completed successfully.")
            return True
        except Exception as e:
            logger.critical(f"FATAL: Rollback failed during restoration: {e}")
            return False

    def apply_update(self, version: str) -> bool:
        """Execute a full, safe update with rollback boundaries."""
        logger.info(f"Applying update: {version}")
        snapshot_dir = self.create_snapshot(reason=f"pre_update_{version}")
        
        try:
            # Step 1: Download new payload (Stub)
            logger.info("Downloading payload...")
            
            # Step 2: Apply file replacements (Stub)
            logger.info("Extracting and applying system files...")
            
            # Step 3: Run database / config migrations
            logger.info("Running schema and config migrations...")
            # Simulate a failure if the version is 'fail'
            if version == "fail":
                raise RuntimeError("Simulated migration failure!")
                
            logger.info(f"Update to {version} successful.")
            return True
            
        except Exception as e:
            logger.error(f"Update failed: {e}. Initiating automatic rollback...")
            self.rollback(snapshot_dir.name)
            return False