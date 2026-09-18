from __future__ import annotations

import sqlite3
from datetime import datetime

from shea.persistence.sqlite.profile_repository import SqliteProfileRepository
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from shea.profiles.models import UserProfile
from shea.profiles.snapshot import ProfileSnapshot


class ProfileService:
    """High-level service for managing and resolving user contexts."""

    def __init__(self, conn: sqlite3.Connection, *, unit_of_work: SqliteUnitOfWork) -> None:
        self._uow = unit_of_work
        self._repo = SqliteProfileRepository(conn, unit_of_work=unit_of_work)

    def get_profile(self, profile_id: str) -> UserProfile | None:
        """Fetch a specific user profile by ID."""
        with self._uow:
            return self._repo.get(profile_id)

    def create_or_update_profile(self, profile: UserProfile) -> None:
        """Create or update a user profile."""
        with self._uow:
            self._repo.save(profile)

    def enrich_intent_content(self, profile_id: str | None, raw_content: str) -> str:
        """Injects user context rules into the intent text if a profile is present."""
        if not profile_id:
            return raw_content
            
        profile = self.get_profile(profile_id)
        if not profile or not profile.context_rules:
            return raw_content
            
        context_block = profile.get_context_injection()
        # Prepend context as a system block so the agent sees it before the actual prompt
        return f"{context_block}\n\nUser Request:\n{raw_content}"

    def list_profiles(self) -> list[UserProfile]:
        with self._uow:
            return self._repo.list_all()

    def freeze(self, profile_id: str | None, *, now: datetime | None = None) -> ProfileSnapshot:
        """Capture a point-in-time snapshot. Call once at task creation."""
        from datetime import UTC
        from datetime import datetime as dt

        when = now or dt.now(tz=UTC)
        pid = profile_id or "system"
        profile = self.get_profile(pid)
        if profile is None:
            return ProfileSnapshot.system(now=when) if pid == "system" else ProfileSnapshot(
                profile_id=pid,
                name=pid,
                frozen_at=when,
            )
        return ProfileSnapshot(
            profile_id=profile.id,
            name=profile.name,
            preferences=dict(profile.preferences),
            context_rules=dict(profile.context_rules),
            frozen_at=when,
        )