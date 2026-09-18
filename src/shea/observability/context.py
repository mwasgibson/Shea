from __future__ import annotations

import contextvars
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

_correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)
_task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "task_id", default=None
)
_profile_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "profile_id", default=None
)

def get_correlation_id() -> str | None:
    return _correlation_id_var.get()

def get_task_id() -> str | None:
    return _task_id_var.get()

def get_profile_id() -> str | None:
    return _profile_id_var.get()

@contextmanager
def active_context(
    *, 
    correlation_id: str | None = None,
    task_id: str | None = None,
    profile_id: str | None = None
) -> Generator[None, None, None]:
    """Temporarily bind tracing values in the current context."""
    tokens: list[tuple[contextvars.ContextVar[Any], contextvars.Token[Any]]] = []
    
    if correlation_id is not None:
        tokens.append((_correlation_id_var, _correlation_id_var.set(correlation_id)))
    if task_id is not None:
        tokens.append((_task_id_var, _task_id_var.set(task_id)))
    if profile_id is not None:
        tokens.append((_profile_id_var, _profile_id_var.set(profile_id)))
        
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
