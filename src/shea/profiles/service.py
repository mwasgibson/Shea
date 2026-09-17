from __future__ import annotations

import sqlite3

from shea.persistence.sqlite.profile_repository import SqliteProfileRepository
from shea.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from shea.profiles.models import UserProfile


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