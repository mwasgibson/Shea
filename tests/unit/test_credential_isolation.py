from datetime import UTC, datetime

import pytest

from shea.bootstrap import build_runtime
from shea.credentials.contracts import CredentialMetadata, CredentialReference
from shea.security.exceptions import SecurityViolationError


class DummySecureStore:
    def __init__(self):
        self.secrets = {}
    def set_secret(self, cred_id, secret):
        self.secrets[cred_id] = secret
    def get_secret(self, cred_id):
        return self.secrets.get(cred_id)
    def delete_secret(self, cred_id):
        self.secrets.pop(cred_id, None)

def test_profile_credential_isolation(tmp_path):


    runtime = build_runtime(tmp_path / "test.db", workspace=tmp_path / "ws")
    runtime.credential_broker._secure_store = DummySecureStore()

    
    # Store credential metadata for Profile A
    meta_a = CredentialMetadata(
        id="cred_A",
        profile_id="profile_A",
        name="api_key",
        description="Profile A API Key",
        allowed_tools=frozenset({"github.*", "network.*"}),
        created_at=datetime.now(UTC)
    )
    runtime.credential_broker._vault.save_metadata(meta_a)
    
    # Store credential metadata for Profile B
    meta_b = CredentialMetadata(
        id="cred_B",
        profile_id="profile_B",
        name="api_key",
        description="Profile B API Key",
        allowed_tools=frozenset({"github.*", "network.*"}),
        created_at=datetime.now(UTC)
    )
    runtime.credential_broker._vault.save_metadata(meta_b)
    
    # Store the actual secrets (broker delegates to secure store)
    runtime.credential_broker._secure_store.set_secret("cred_A", "secret_A")
    runtime.credential_broker._secure_store.set_secret("cred_B", "secret_B")
    
    ref_a = CredentialReference(id="cred_A", name="cred_A", description=None)
    ref_b = CredentialReference(id="cred_B", name="cred_B", description=None)
    
    # Profile A should be able to resolve its own credential
    cred = runtime.credential_broker.resolve(ref_a, "network.fetch", "profile_A")
    assert cred.secret_value == "secret_A"
    
    # Profile A should NOT be able to resolve Profile B's credential
    with pytest.raises(SecurityViolationError) as exc:
        runtime.credential_broker.resolve(ref_b, "network.fetch", "profile_A")
    assert "not authorized to access" in str(exc.value)
    
    # Profile B should be able to resolve its own credential
    cred2 = runtime.credential_broker.resolve(ref_b, "network.fetch", "profile_B")
    assert cred2.secret_value == "secret_B"
    
