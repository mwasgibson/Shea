from __future__ import annotations

import keyring
from keyring.errors import PasswordDeleteError

from shea.credentials.ports import SecureStore


class KeyringSecureStore(SecureStore):
    """Stores secrets in the OS's native secure enclave using the `keyring` library.
    
    macOS: Keychain
    Linux: Secret Service or KWallet
    Windows: Windows Credential Locker
    """

    def __init__(self, service_name: str = "shea_agent") -> None:
        self._service_name = service_name

    def set_secret(self, credential_id: str, secret: str) -> None:
        keyring.set_password(self._service_name, credential_id, secret)

    def get_secret(self, credential_id: str) -> str | None:
        return keyring.get_password(self._service_name, credential_id)

    def delete_secret(self, credential_id: str) -> None:
        try:
            keyring.delete_password(self._service_name, credential_id)
        except PasswordDeleteError:
            # If the password didn't exist, we don't care during deletion
            pass