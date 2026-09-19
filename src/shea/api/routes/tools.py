# src/shea/api/routes/tools.py
from fastapi import APIRouter, Depends, Request
from typing import Annotated, cast
from shea.bootstrap import SheaRuntime

router = APIRouter(prefix="/tools", tags=["Tools"])

def get_runtime(request: Request) -> SheaRuntime:
    return cast(SheaRuntime, request.app.state.runtime)

@router.get("/")
async def list_tools(runtime: Annotated[SheaRuntime, Depends(get_runtime)]) -> list[dict[str, str | list[str]]]:
    decls = runtime.tool_registry.list_tools()
    return [
        {
            "name": d.name,
            "capabilities": sorted(d.capabilities),
            "description": d.description,
        }
        for d in decls
    ]