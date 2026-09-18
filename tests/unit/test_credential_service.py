from shea.bootstrap import build_runtime


class DummySecureStore:
    def __init__(self):
        self.secrets = {}
    def set_secret(self, cred_id, secret):
        self.secrets[cred_id] = secret
    def get_secret(self, cred_id):
        return self.secrets.get(cred_id)
    def delete_secret(self, cred_id):
        self.secrets.pop(cred_id, None)

def test_credential_lifecycle(tmp_path):
    runtime = build_runtime(tmp_path / "test.db", workspace=tmp_path / "ws")
    runtime.credential_service._secure_store = DummySecureStore()
    
    # 1. Creation
    meta = runtime.credential_service.create(
        profile_id="prof_1",
        name="api_token",
        description="Test Token",
        allowed_tools=frozenset({"tool.a"}),
        secret="super_secret"
    )
    
    assert meta.profile_id == "prof_1"
    assert meta.name == "api_token"
    assert runtime.credential_service._secure_store.get_secret(meta.id) == "super_secret"
    
    # 2. Rotation
    runtime.credential_service.rotate(meta.id, "new_secret")
    assert runtime.credential_service._secure_store.get_secret(meta.id) == "new_secret"
    
    # 3. Scoping
    runtime.credential_service.update_scopes(meta.id, frozenset({"tool.b"}))
    updated_meta = runtime.credential_broker._vault.get_metadata(meta.id)
    assert updated_meta.allowed_tools == frozenset({"tool.b"})
    
    # 4. Redaction
    text = "Here is the new_secret in a log message."
    redacted = runtime.credential_service.redact(text)
    assert redacted == "Here is the [REDACTED_CREDENTIAL] in a log message."
    
    # 5. Revocation
    runtime.credential_service.revoke(meta.id)
    assert runtime.credential_broker._vault.get_metadata(meta.id) is None
    assert runtime.credential_service._secure_store.get_secret(meta.id) is None

