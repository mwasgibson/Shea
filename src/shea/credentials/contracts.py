from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CredentialReference:
    """A safe pointer to a credential, suitable for passing to tools.
    
    This does NOT contain the secret itself. It is used by the tool
    to request the actual secret from the broker during execution.
    """
    id: str
    name: str                  # e.g., 'github_token'
    description: str | None


@dataclass(frozen=True)
class ScopedCredential:
    """The fully resolved credential, including the secret value."""
    id: str
    name: str
    secret_value: str          # The actual token/key


@dataclass(frozen=True)
class CredentialMetadata:
    """Metadata and access control rules for a stored credential."""
    id: str
    name: str
    description: str | None
    allowed_tools: frozenset[str]  # Which tools can request this credential (e.g. 'github.*')
    created_at: datetime
    updated_at: datetime | None = None