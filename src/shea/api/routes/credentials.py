from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request

from shea.api.contracts import CredentialCreateRequest, CredentialView
from shea.bootstrap import SheaRuntime

router = APIRouter(prefix="/credentials", tags=["Credentials"])


def get_runtime(request: Request) -> SheaRuntime:
    return cast(SheaRuntime, request.app.state.runtime)


def _to_view(m: Any) -> CredentialView:
    return CredentialView(
        id=m.id,
        profile_id=m.profile_id,
        name=m.name,
        description=m.description,
        allowed_tools=sorted(m.allowed_tools),
        created_at=m.created_at.isoformat(),
        updated_at=m.updated_at.isoformat() if m.updated_at else None,
    )


@router.get("/", response_model=list[CredentialView])
async def list_credentials(
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
    profile_id: str | None = None,
) -> list[CredentialView]:
    """List credential *references* only. Secrets never leave the secure store."""
    metas = runtime.credential_service.list_metadata(profile_id=profile_id)
    return [_to_view(m) for m in metas]


@router.post("/", response_model=CredentialView)
async def create_credential(
    payload: CredentialCreateRequest,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> CredentialView:
    meta = runtime.credential_service.create(
        profile_id=payload.profile_id,
        name=payload.name,
        description=payload.description or "",
        allowed_tools=frozenset(payload.allowed_tools),
        secret=payload.secret,
    )
    return _to_view(meta)


@router.delete("/{credential_id}")
async def revoke_credential(
    credential_id: str,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> dict[str, str]:
    try:
        runtime.credential_service.revoke(credential_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "revoked", "id": credential_id}