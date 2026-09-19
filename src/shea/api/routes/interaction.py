from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from shea.api.contracts import ChatRequest, ChatResponse, ConfirmRequest
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

    The API must never bypass the existing pipeline (Text → Intent → Plan → Execute).
    We dispatch this synchronously to the InteractionService so it flows through the exact
    same execution and security paths as the CLI.
    """
    session_id: str = payload.session_id or uuid4().hex
    profile_id: str = payload.profile_id or "default"

    def run_pipeline() -> None:
        # Using interaction_service.handle_text enforces the full cognition pipeline
        runtime.interaction_service.handle_text(
            text=payload.message,
            session_id=session_id,
            profile_id=profile_id,
            explicit_user_ack=False,
            actor="api-user",
            run=True,
        )

    # In a fully asynchronous core we would await this.
    # For our synchronous architectural core, we run it in a background thread
    # to avoid blocking the ASGI event loop, while live logs stream out via SSE.
    background_tasks.add_task(run_pipeline)

    return ChatResponse(
        text="Accepted. Watch /api/interaction/stream.",
        session_id=session_id,
        task_id=None,
        needs_confirmation=False,
        confirmation=None,
        state=None,
    )


@router.post("/confirm", response_model=ChatResponse)
async def confirm_task(
    payload: ConfirmRequest,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> ChatResponse:
    pending = runtime.pending_confirmations.pop(payload.task_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="no pending confirmation for task")
    if not payload.acknowledge:
        runtime.orchestrator.advance(payload.task_id, "cancel")
        return ChatResponse(
            text="Cancelled by user.",
            session_id=pending.session_id,
            task_id=payload.task_id,
            state="CANCELLED",
        )

    result = runtime.interaction_service.confirm_and_run(
        payload.task_id, actor=payload.actor, explicit_user_ack=True
    )
    return ChatResponse(
        text="Confirmed and running." if result.error is None else result.error,
        session_id=pending.session_id,
        task_id=payload.task_id,
        state=result.task.state.value,
    )


@router.get("/pending")
async def list_pending(
    session_id: str,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> list[dict[str, Any]]:
    items = runtime.pending_confirmations.list_for_session(session_id)
    return [
        {
            "task_id": p.task_id,
            "risk": p.risk,
            "explanation": p.explanation,
            "capabilities": p.capabilities,
        }
        for p in items
    ]


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