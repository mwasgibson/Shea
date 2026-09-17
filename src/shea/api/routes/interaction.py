from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from shea.api.contracts import ChatRequest, ChatResponse
from shea.bootstrap import SheaRuntime
from shea.contracts.models import Intent
from shea.events.contracts import Event

# We will attach the runtime to app.state in server.py
router = APIRouter(prefix="/interaction", tags=["Interaction"])


def get_runtime(request: Request) -> SheaRuntime:
    return cast(SheaRuntime, request.app.state.runtime)


@router.post("/chat", response_model=ChatResponse)
async def submit_chat(
    payload: ChatRequest,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> ChatResponse:
    """Submit a chat message in request-response mode.

    In a real unified app, SSE is preferred for live streaming, but this serves
    as the fallback / stateless submission endpoint.
    """
    now = datetime.now(UTC)
    intent_id = uuid4().hex
    enriched_content = runtime.profile_service.enrich_intent_content(
        payload.profile_id, payload.message
    )
    intent = Intent(
        id=intent_id,
        task_id=uuid4().hex,
        type="chat",
        goal=enriched_content,
        parameters={
            "profile_id": payload.profile_id or "default",
            "context_overrides": payload.context_overrides,
        },
        source="api",
        created_at=now,
    )

    runtime.event_bus.publish(
        Event(
            event_id=uuid4().hex,
            event_type="interaction.intent_received",
            source="api",
            timestamp=now,
            payload={
                "intent_id": intent.id,
                "task_id": intent.task_id,
                "goal": intent.goal,
                "profile_id": payload.profile_id or "default",
            },
            correlation_id=intent.id,
        )
    )

    return ChatResponse(
        text=f"Acknowledged intent: {intent.id}",
        session_id=intent.id,
    )


@router.get("/stream")
async def event_stream(
    request: Request,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> EventSourceResponse:
    """Server-Sent Events (SSE) endpoint for live interaction and tool execution updates."""

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        # We hook a queue into the EventBus for the duration of the stream
        queue: asyncio.Queue[Event] = asyncio.Queue()

        def _on_event(event: Event) -> None:
            # Non-blocking put since the bus runs synchronously
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

        subscription_id = runtime.event_bus.subscribe("*", _on_event)

        try:
            while True:
                if await request.is_disconnected():
                    break

                event = await queue.get()
                yield {
                    "event": event.event_type,
                    "data": json.dumps(event.payload),
                }
        finally:
            runtime.event_bus.unsubscribe(subscription_id)

    return EventSourceResponse(event_generator())