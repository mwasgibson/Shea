from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sse_starlette.sse import EventSourceResponse

from shea.api.contracts import ChatRequest, ChatResponse
from shea.bootstrap import SheaRuntime
from shea.events.contracts import Event

# We will attach the runtime to app.state in server.py
router = APIRouter(prefix="/interaction", tags=["Interaction"])


def get_runtime(request: Request) -> SheaRuntime:
    return cast(SheaRuntime, request.app.state.runtime)


@router.post("/chat", response_model=ChatResponse)
async def submit_chat(
    payload: ChatRequest,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
    background_tasks: BackgroundTasks,
) -> ChatResponse:
    """Submit a chat message via the core InteractionService pipeline.
    
    The API must never bypass the existing pipeline (Text -> Intent -> Plan -> Execute).
    We dispatch this synchronously to the InteractionService so it flows through the exact
    same execution and security paths as the CLI.
    """
    
    def run_pipeline() -> None:
        profile_id = payload.profile_id or "default"
        # Using interaction_service.handle_text enforces the full cognition pipeline
        runtime.interaction_service.handle_text(
            text=payload.message,
            session_id=payload.session_id or uuid4().hex,
            profile_id=profile_id,
            explicit_user_ack=False, # Wait, for API, do we block on ack? Assuming auto-run or event-based ack for now
        )
        
    # In a fully asynchronous core we would await this.
    # For our synchronous architectural core, we run it in a background thread 
    # to avoid blocking the ASGI event loop, while live logs stream out via SSE.
    background_tasks.add_task(run_pipeline)
    
    return ChatResponse(
        text="Processing via InteractionService. Connect to /api/interaction/stream for updates.",
        session_id=payload.session_id or "new",
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