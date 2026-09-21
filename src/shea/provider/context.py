from contextvars import ContextVar
from typing import Optional

preferred_provider_ctx: ContextVar[Optional[str]] = ContextVar("preferred_provider", default=None)