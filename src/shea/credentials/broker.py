from __future__ import annotations

from shea.credentials.contracts import CredentialReference, ScopedCredential
from shea.credentials.ports import CredentialBroker, SecureStore, VaultRepository
from shea.events.filters import _pattern_matches  # pyright: ignore[reportPrivateUsage]
from shea.security.exceptions import SecurityViolationError


class SheaCredentialBroker(CredentialBroker):
    """Enforces access policies before dispensing secrets to tools."""

    def __init__(self, vault: VaultRepository, secure_store: SecureStore) -> None:
        self._vault = vault
        self._secure_store = secure_store

    def _is_tool_allowed(self, tool_name: str, allowed_patterns: frozenset[str]) -> bool:
        """Check if the requesting tool matches any of the allowed patterns."""
        for pattern in allowed_patterns:
            if _pattern_matches(pattern, tool_name):
                return True
        return False

    def resolve(self, reference: CredentialReference, requesting_tool: str) -> ScopedCredential:
        """Resolves a reference into a secret if the tool is authorized."""
        
        metadata = self._vault.get_metadata(reference.id)
        if metadata is None:
            raise ValueError(f"Credential '{reference.id}' does not exist in the vault.")

        if not self._is_tool_allowed(requesting_tool, metadata.allowed_tools):
            raise SecurityViolationError(
                category="credential_access",
                tool_name=requesting_tool,
                reason=(
                    f"Tool '{requesting_tool}' is not authorized to access "
                    f"credential '{metadata.name}'."
                ),
            )

        secret = self._secure_store.get_secret(reference.id)
        if secret is None:
            raise ValueError(
                f"Secret for credential '{reference.id}' is missing from the secure store."
            )

        return ScopedCredential(
            id=metadata.id,
            name=metadata.name,
            secret_value=secret,
        )