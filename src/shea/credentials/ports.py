from __future__ import annotations

from typing import Protocol

from shea.credentials.contracts import CredentialMetadata, CredentialReference, ScopedCredential


class VaultRepository(Protocol):
    """Durable storage for credential metadata (access controls).
    
    This does NOT store the secret values, only who is allowed to access them.
    """

    def save_metadata(self, metadata: CredentialMetadata) -> None:
        ...

    def get_metadata(self, credential_id: str) -> CredentialMetadata | None:
        ...

    def list_metadata(self) -> list[CredentialMetadata]:
        ...

    def delete_metadata(self, credential_id: str) -> None:
        ...


class SecureStore(Protocol):
    """Interface to the host OS's secure enclave (Keychain, Keyring).
    
    This is strictly for storing and retrieving the raw secret bytes.
    """

    def set_secret(self, credential_id: str, secret: str) -> None:
        ...

    def get_secret(self, credential_id: str) -> str | None:
        ...

    def delete_secret(self, credential_id: str) -> None:
        ...


class CredentialBroker(Protocol):
    """The authority for dispensing credentials to tools."""

    def resolve(self, reference: CredentialReference, requesting_tool: str) -> ScopedCredential:
        """Resolves a reference into a secret, enforcing access policies.
        
        Raises:
            SecurityViolationError: If the tool is not authorized for this credential.
            ValueError: If the credential does not exist.
        """
        ...