from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """A user submitted chat message or command."""
    message: str = Field(..., description="The textual input from the user.")
    profile_id: str | None = Field(None, description="Optional profile identifier.")
    context_overrides: dict[str, Any] = Field(
        default_factory=dict, 
        description="Overrides for the session context."
        )


class ChatResponse(BaseModel):
    """A single atomic text response from the agent (for non-streaming interactions)."""
    text: str = Field(..., description="The response text.")
    session_id: str = Field(..., description="The interaction session ID.")


class ErrorResponse(BaseModel):
    """Standardized API error response."""
    detail: str = Field(..., description="Error message.")
    code: str | None = Field(None, description="Optional application-specific error code.")


class MemoryView(BaseModel):
    """A flattened representation of a memory for the GUI."""
    id: str
    content: str
    source: str
    type: str
    created_at: str
    expires_at: str | None
    confidence: float