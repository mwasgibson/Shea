from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request

from shea.api.contracts import ProfileUpsertRequest, ProfileView
from shea.bootstrap import SheaRuntime
from shea.profiles.models import UserProfile

router = APIRouter(prefix="/profiles", tags=["Profiles"])


def get_runtime(request: Request) -> SheaRuntime:
    return cast(SheaRuntime, request.app.state.runtime)


def _to_view(p: UserProfile) -> ProfileView:
    return ProfileView(
        id=p.id,
        name=p.name,
        preferences=dict(p.preferences),
        context_rules=dict(p.context_rules),
        created_at=p.created_at.isoformat() if p.created_at else None,
        updated_at=p.updated_at.isoformat() if p.updated_at else None,
    )


@router.get("/", response_model=list[ProfileView])
async def list_profiles(
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> list[ProfileView]:
    return [_to_view(p) for p in runtime.profile_service.list_profiles()]


@router.get("/{profile_id}", response_model=ProfileView)
async def get_profile(
    profile_id: str,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> ProfileView:
    profile = runtime.profile_service.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return _to_view(profile)


@router.put("/{profile_id}", response_model=ProfileView)
async def upsert_profile(
    profile_id: str,
    payload: ProfileUpsertRequest,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> ProfileView:
    if payload.id != profile_id:
        raise HTTPException(status_code=400, detail="path id and body id must match")
    existing = runtime.profile_service.get_profile(profile_id)
    now = datetime.now(tz=UTC)
    profile = UserProfile(
        id=profile_id,
        name=payload.name,
        preferences=payload.preferences,
        context_rules=payload.context_rules,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    runtime.profile_service.create_or_update_profile(profile)
    saved = runtime.profile_service.get_profile(profile_id)
    if saved is None:
        raise HTTPException(status_code=500, detail="profile save failed")
    return _to_view(saved)