from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from shea.credentials.injection import CREDENTIAL_REF_KEY
from shea.security.exceptions import SecurityViolationError


def credential_ref_for_host(
    hostname: str,
    destination_credentials: dict[str, str],
) -> str | None:
    """Map host → credential id from scope. Exact host match only (V1)."""
    host = hostname.lower().rstrip(".")
    if host in destination_credentials:
        return destination_credentials[host]
    return None


def bind_destination_credential_ref(
    arguments: dict[str, Any],
    *,
    url: str,
    destination_credentials: dict[str, str],
    arg_name: str = "authorization",
) -> dict[str, Any]:
    """Attach a credential *reference* for this host — never the secret.

    Only injects a ref marker if:
      - destination_credentials has this host
      - arguments do not already contain a secret string for arg_name
    """
    host = urlparse(url).hostname
    if not host:
        return arguments
    cred_id = credential_ref_for_host(host, destination_credentials)
    if cred_id is None:
        return arguments

    out = dict(arguments)
    existing = out.get(arg_name)
    if isinstance(existing, str) and existing and not (
        isinstance(existing, dict)
    ):
        # Raw secret in arguments is a boundary violation
        raise SecurityViolationError(
            "network",
            "credential",
            f"raw secret material in arguments[{arg_name!r}] is forbidden; "
            "use credential refs only",
        )
    if is_ref(existing):
        return out
    out[arg_name] = {
        CREDENTIAL_REF_KEY: cred_id,
        "name": cred_id,
        "bound_host": host.lower(),
    }
    return out


def is_ref(value: object) -> bool:
    return isinstance(value, dict) and CREDENTIAL_REF_KEY in value