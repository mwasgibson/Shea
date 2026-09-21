from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import UploadFile, File
import shutil
from pathlib import Path
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from shea.api.contracts import ChatRequest, ChatResponse, ConfirmRequest
from shea.bootstrap import SheaRuntime
from shea.events.contracts import Event

# We will attach the runtime to app.state in server.py
router = APIRouter(prefix="/interaction", tags=["Interaction"])


def get_runtime(request: Request) -> SheaRuntime:
    return cast(SheaRuntime, request.app.state.runtime)



@router.post("/upload")
async def upload_file(
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
    file: UploadFile = File(...),
) -> dict[str, str]:
    workspace = Path(os.environ.get("SHEA_WORKSPACE", "./workspace")).resolve()
    uploads_dir = workspace / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate unique filename to avoid collisions
    safe_name = f"{uuid4().hex[:8]}_{file.filename or 'upload'}"
    target_path = uploads_dir / safe_name
    
    with target_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
        
    return {
        "filename": file.filename or "unknown",
        "path": str(target_path),
        "url": f"/api/interaction/uploads/{safe_name}"
    }


@router.get("/history")
def get_history(
    session_id: str,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> list[dict[str, Any]]:
    return runtime.chat_repository.get_history(session_id)

@router.get("/sessions")
def get_sessions(
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> list[dict[str, str]]:
    return runtime.chat_repository.get_all_sessions()

@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> dict[str, str]:
    runtime.chat_repository.delete_session(session_id)
    return {"status": "success"}

@router.post("/chat", response_model=ChatResponse)
def submit_chat(
    payload: ChatRequest,
    runtime: Annotated[SheaRuntime, Depends(get_runtime)],
) -> ChatResponse:
    """Submit a chat message via the core InteractionService pipeline.

    The API must never bypass the existing pipeline (Text → Intent → Plan → Execute).
    We dispatch this synchronously to the InteractionService so it flows through the exact
    same execution and security paths as the CLI.
    """

    session_id: str = payload.session_id or uuid4().hex
    profile_id: str = payload.profile_id or "default"

    from shea.provider.context import preferred_provider_ctx
    provider_override = payload.context_overrides.get("model_provider")
    token = None
    if provider_override:
        token = preferred_provider_ctx.set(provider_override)

    try:
        # Incorporate attachments from context_overrides into the message
        msg_text = payload.message
        attachments = payload.context_overrides.get("attachments", [])
        if attachments:
            msg_text += "\n\n[Attached Files in Workspace]\n"
            for att in attachments:
                msg_text += f"- {att.get('name')} -> {att.get('path')}\n"

        # Save user message to chat history
        from datetime import datetime, UTC
        runtime.chat_repository.save_event(
            event_id=uuid4().hex,
            session_id=session_id,
            source="user",
            event_type="message",
            content=msg_text,
            created_at=datetime.now(UTC).isoformat()
        )

        # Using interaction_service.handle_text enforces the full cognition pipeline
        result = runtime.interaction_service.handle_text(
            text=msg_text,
            session_id=session_id,
            profile_id=profile_id,
            explicit_user_ack=False,
            actor="api-user",
            run=True,
        )

        needs_confirmation = result.error == "authorization_required"
        
        response_text = "Requires confirmation" if needs_confirmation else "Done."
        if result.task:
            plan = runtime.plan_repository.get_by_task(result.task.id)
            if plan:
                for step in reversed(plan.steps):
                    if step.tool == "system.reply" and step.state == "COMPLETED":
                        reply_msg: object = step.arguments.get("message")
                        if isinstance(reply_msg, str):
                            response_text = reply_msg
                        break
                    
        if response_text not in ("Requires confirmation", "Done."):
            # Save agent reply to DB so history works
            from datetime import datetime, UTC
            runtime.chat_repository.save_event(
                event_id=uuid4().hex,
                session_id=session_id,
                source="agent",
                event_type="message",
                content=response_text,
                created_at=datetime.now(UTC).isoformat()
            )

        return ChatResponse(
            text=response_text,
            session_id=session_id,
            task_id=result.task.id if result.task else None,
            needs_confirmation=needs_confirmation,
            confirmation={"decision_id": result.pending_decision.id} if needs_confirmation and result.pending_decision else None,
            state=result.task.state.value if result.task else None,
        )
    finally:
        if token:
            preferred_provider_ctx.reset(token)


@router.post("/confirm", response_model=ChatResponse)
def confirm_task(
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
    
    error_str = result.error if isinstance(result.error, str) else "Confirmed and executed."
    response_text = error_str
    
    if result.task:
        plan = runtime.plan_repository.get_by_task(result.task.id)
        if plan:
            for step in reversed(plan.steps):
                if step.tool == "system.reply" and step.state == "COMPLETED":
                    reply_msg: object = step.arguments.get("message")
                    if isinstance(reply_msg, str):
                        response_text = reply_msg
                    break
                
    if response_text not in ("Confirmed and executed.", "Cancelled by user.") and not result.error:
        from datetime import datetime, UTC
        runtime.chat_repository.save_event(
            event_id=uuid4().hex,
            session_id=pending.session_id,
            source="agent",
            event_type="message",
            content=response_text,
            created_at=datetime.now(UTC).isoformat()
        )
        
    return ChatResponse(
        text=response_text,
        session_id=pending.session_id,
        task_id=result.task.id if result.task else None,
        needs_confirmation=False,
        state=result.task.state.value if result.task else None,
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