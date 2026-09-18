from __future__ import annotations

from typing import Any, cast

from shea.credentials.contracts import CredentialReference
from shea.credentials.ports import CredentialBroker

CREDENTIAL_REF_KEY = "__credential_ref__"


def is_credential_ref(value: object) -> bool:
    return isinstance(value, dict) and CREDENTIAL_REF_KEY in value


def resolve_argument_credentials(
    arguments: dict[str, Any],
    *,
    broker: CredentialBroker,
    tool: str,
    profile_id: str,
) -> dict[str, Any]:
    """Replace credential refs with secrets at the final injection point only.

    Input must stay reference-shaped through contract / receipt / permit.
    Secrets exist only in the returned dict passed to the handler.
    """
    resolved: dict[str, Any] = dict(arguments)
    for key, value in arguments.items():
        if not is_credential_ref(value):
            continue
        value = cast(dict[str, Any], value)
        ref_id = str(value[CREDENTIAL_REF_KEY])
        ref = CredentialReference(
            id=ref_id,
            name=str(value.get("name", ref_id)),
            description=(
                str(value["description"])
                if value.get("description") is not None
                else None
            ),
        )
        scoped = broker.resolve(ref, tool, profile_id)
        resolved[key] = scoped.secret_value
    return resolved