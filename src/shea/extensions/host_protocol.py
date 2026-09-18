from __future__ import annotations

from typing import Any, TypedDict


class HostRequest(TypedDict):
    id: str
    method: str
    params: dict[str, Any]


class HostResponse(TypedDict):
    id: str
    ok: bool
    result: dict[str, Any] | None
    error: str | None