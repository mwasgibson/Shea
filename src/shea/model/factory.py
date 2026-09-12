from __future__ import annotations

import os

from shea.model.model_compatible import ModelCompatibleProvider
from shea.ports.model_provider import ModelProvider


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip() != "":
            return value.strip()
    return default


def model_provider_from_env() -> ModelProvider | None:
    """Build a ModelProvider from the process environment.

    Supported SHEA_MODEL_PROVIDER values:
      puter | ollama | openai | ghost | anthropic

    If SHEA_MODEL_PROVIDER is unset, auto-detect in order:
      SHEA_PUTER_TOKEN → puter
      GHOST_API_KEY / GHOST_BASE_URL → ghost
      OPENAI_API_KEY → openai-compatible
      else → None (template-only planning)
    """
    kind = (_env("SHEA_MODEL_PROVIDER") or "").lower()

    if not kind:
        if _env("SHEA_PUTER_TOKEN"):
            kind = "puter"
        elif _env("GHOST_API_KEY", "GHOST_BASE_URL"):
            kind = "ghost"
        elif _env("OPENAI_API_KEY", "SHEA_MODEL_API_KEY"):
            kind = "openai"
        else:
            return None

    if kind == "puter":
        token = _env("SHEA_PUTER_TOKEN", "SHEA_MODEL_API_KEY")
        if not token:
            return None
        return ModelCompatibleProvider(
            api_key=token,
            base_url=_env(
                "SHEA_MODEL_BASE_URL",
                default="https://api.puter.com/puterai/openai/v1",
            )
            or "https://api.puter.com/puterai/openai/v1",
            model=_env("SHEA_MODEL_NAME", default="gpt-5.4-nano") or "gpt-5.4-nano",
            timeout_seconds=float(_env("SHEA_MODEL_TIMEOUT", default="60") or "60"),
            name="puter",
            use_json_response_format=False,
        )

    if kind == "ollama":
        return ModelCompatibleProvider(
            api_key=_env("SHEA_MODEL_API_KEY", default="ollama") or "ollama",
            base_url=_env(
                "SHEA_MODEL_BASE_URL",
                default="http://127.0.0.1:11434/v1",
            )
            or "http://127.0.0.1:11434/v1",
            model=_env("SHEA_MODEL_NAME", default="llama3.2") or "llama3.2",
            timeout_seconds=float(_env("SHEA_MODEL_TIMEOUT", default="120") or "120"),
            name="ollama",
            use_json_response_format=False,
        )

    if kind in {"ghost", "openai", "anthropic"}:
        # ghost.thesapientcompany.com and similar OpenAI-compatible gateways
        api_key = _env(
            "GHOST_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "SHEA_MODEL_API_KEY",
        )
        if not api_key:
            return None
        base_url = _env(
            "GHOST_BASE_URL",
            "OPENAI_BASE_URL",
            "ANTHROPIC_BASE_URL",
            "SHEA_MODEL_BASE_URL",
            default="https://api.openai.com/v1",
        ) or "https://api.openai.com/v1"
        model = _env(
            "GHOST_MODEL",
            "OPENAI_MODEL",
            "ANTHROPIC_MODEL",
            "SHEA_MODEL_NAME",
            default="gpt-4o-mini",
        ) or "gpt-4o-mini"
        # Normalize names like ghost-x1(openai) → ghost-x1 if the gateway wants bare ids
        if "(" in model:
            model = model.split("(", 1)[0].strip()
        return ModelCompatibleProvider(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model=model,
            timeout_seconds=float(_env("SHEA_MODEL_TIMEOUT", default="60") or "60"),
            name=kind,
            use_json_response_format=_env("SHEA_MODEL_JSON_FORMAT", default="0") == "1",
        )

    # Unknown kind: treat as generic openai-compatible using SHEA_* only
    api_key = _env("SHEA_MODEL_API_KEY", "OPENAI_API_KEY")
    if not api_key:
        return None
    return ModelCompatibleProvider(
        api_key=api_key,
        base_url=(_env("SHEA_MODEL_BASE_URL", default="https://api.openai.com/v1") or "").rstrip(
            "/"
        ),
        model=_env("SHEA_MODEL_NAME", default="gpt-4o-mini") or "gpt-4o-mini",
        timeout_seconds=float(_env("SHEA_MODEL_TIMEOUT", default="60") or "60"),
        name=kind or "openai_compatible",
        use_json_response_format=False,
    )