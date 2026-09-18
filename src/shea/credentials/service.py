from __future__ import annotations

import re
import threading
from dataclasses import replace

from shea.credentials.contracts import CredentialMetadata
from shea.credentials.ports import SecureStore, VaultRepository
from shea.events.channels import CredentialChannel
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator


class CredentialService:
    """Manages the lifecycle of credentials: Creation, Rotation, Revocation, Scoping, and Redaction."""

    def __init__(self, vault: VaultRepository, secure_store: SecureStore, ids: IdGenerator, clock: Clock, channel: CredentialChannel | None = None):
        self._vault = vault
        self._secure_store = secure_store
        self._ids = ids
        self._clock = clock
        self._channel = channel
        
        self._redaction_lock = threading.Lock()
        self._redaction_pattern: re.Pattern[str] | None = None


    def _invalidate_redaction_cache(self) -> None:
        with self._redaction_lock:
            self._redaction_pattern = None

    def _get_redaction_pattern(self) -> re.Pattern[str] | None:
        with self._redaction_lock:
            if self._redaction_pattern is not None:
                return self._redaction_pattern
                
            metas = self._vault.list_metadata()
            secrets_to_mask: list[str] = []
            for meta in metas:
                secret = self._secure_store.get_secret(meta.id)
                # Ignore weak/short secrets to avoid destroying common words or short numbers
                if secret and len(secret) >= 8:
                    # Using named capture groups to identify WHICH credential it was would be ideal,
                    # but python regex limits group count. We'll just do a global OR and generic replace.
                    secrets_to_mask.append(re.escape(secret))
            
            if not secrets_to_mask:
                # No secrets to redact, compile a regex that matches nothing
                self._redaction_pattern = re.compile(r'(?!x)x')
            else:
                combined_pattern = "|".join(secrets_to_mask)
                self._redaction_pattern = re.compile(combined_pattern)
                
            return self._redaction_pattern

    def create(self, profile_id: str, name: str, description: str, allowed_tools: frozenset[str], secret: str) -> CredentialMetadata:
        cred_id = self._ids.new_id()
        meta = CredentialMetadata(
            id=cred_id,
            profile_id=profile_id,
            name=name,
            description=description,
            allowed_tools=allowed_tools,
            created_at=self._clock.now()
        )
        self._vault.save_metadata(meta)
        self._secure_store.set_secret(cred_id, secret)
        self._invalidate_redaction_cache()
        if self._channel:
            self._channel.created(cred_id, profile_id)
        return meta
        
    def rotate(self, credential_id: str, new_secret: str) -> None:
        meta = self._vault.get_metadata(credential_id)
        if not meta:
            raise ValueError(f"Credential {credential_id} not found")
        new_meta = replace(meta, updated_at=self._clock.now())
        self._vault.save_metadata(new_meta)
        self._secure_store.set_secret(credential_id, new_secret)
        self._invalidate_redaction_cache()
        if self._channel:
            self._channel.rotated(credential_id)
        
    def revoke(self, credential_id: str) -> None:
        self._vault.delete_metadata(credential_id)
        try:
            self._secure_store.delete_secret(credential_id)
            self._invalidate_redaction_cache()
        except Exception:
            pass # Already gone from OS keyring or similar
        if self._channel:
            self._channel.revoked(credential_id)
        
    def update_scopes(self, credential_id: str, allowed_tools: frozenset[str]) -> None:
        meta = self._vault.get_metadata(credential_id)
        if not meta:
            raise ValueError(f"Credential {credential_id} not found")
        new_meta = replace(meta, allowed_tools=allowed_tools, updated_at=self._clock.now())
        self._vault.save_metadata(new_meta)
        
    def redact(self, text: str) -> str:
        """Scan text and redact known secret strings using a cached, pre-compiled Regex."""
        if not text:
            return text
            
        pattern = self._get_redaction_pattern()
        if pattern:
            return pattern.sub("[REDACTED_CREDENTIAL]", text)
        return text

    def list_metadata(self, profile_id: str | None = None) -> list[CredentialMetadata]:
        """Return credential metadata only — never secret values."""
        metas = self._vault.list_metadata()
        if profile_id is None:
            return metas
        return [m for m in metas if m.profile_id == profile_id]