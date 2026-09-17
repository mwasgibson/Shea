from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from shea.api.contracts import MemoryView
from shea.bootstrap import SheaRuntime

router = APIRouter(prefix="/memory", tags=["Memory"])


def get_runtime(request: Request) -> SheaRuntime:
    return cast(SheaRuntime, request.app.state.runtime)


@router.get("/", response_model=list[MemoryView])
async def list_memories(
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
    profile_id: str = "default",
) -> list[MemoryView]:
    """Retrieve the active memories for a profile."""
    memories = runtime.memory_service.list_active(profile_id)

    return [
        MemoryView(
            id=m.id,
            content=m.content,
            source=m.source,
            type=m.type.value,
            created_at=m.created_at.isoformat(),
            expires_at=m.expires_at.isoformat() if m.expires_at else None,
            confidence=m.confidence,
        )
        for m in memories
    ]


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> dict[str, str]:
    """Hard-delete a memory."""
    runtime.memory_service.delete(memory_id)
    return {"status": "deleted", "id": memory_id}