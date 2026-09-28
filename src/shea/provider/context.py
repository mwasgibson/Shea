from contextvars import ContextVar

preferred_provider_ctx: ContextVar[str | None] = ContextVar("preferred_provider", default=None)