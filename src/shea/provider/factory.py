from __future__ import annotations

import os

from shea.audit.recorder import AuditRecorder
from shea.model.model_compatible import ModelCompatibleProvider
from shea.provider.profile import ProviderProfile, ProviderTrustLevel
from shea.provider.requirements import RoutingRequirements
from shea.provider.router import ProviderRouter
from shea.provider.service import ProviderRoutingService, RegisteredProvider


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip() != "":
            return value.strip()
    return default

def build_provider_routing_service(audit: AuditRecorder, requirements: RoutingRequirements | None = None) -> ProviderRoutingService:
    registered: list[RegisteredProvider] = []

    # 1. Ollama (LOCAL)
    ollama_url = _env("OLLAMA_BASE_URL", default="http://127.0.0.1:11434/v1") or "http://127.0.0.1:11434/v1"
    ollama_model = _env("OLLAMA_MODEL", default="llama3.2") or "llama3.2"
    # If the user explicitly provided Ollama credentials or we just check if it's there
    # We always register the local fallback if possible, though if the URL is unreachable, it will fail health checks
    # But usually we only register if an explicit env var is provided for it?
    # Let's check for OLLAMA_MODEL explicitly or just register it by default
    if ollama_url:
        provider = ModelCompatibleProvider(
            api_key="ollama",
            base_url=ollama_url,
            model=ollama_model,
            timeout_seconds=120.0,
            name="ollama",
            use_json_response_format=False,
        )
        profile = ProviderProfile(
            provider_id="ollama-local",
            model_id=ollama_model,
            trust_level=ProviderTrustLevel.LOCAL,
            capabilities=frozenset({"chat", "tools"}),
            context_limit=8000,
        )
        registered.append(RegisteredProvider(profile=profile, provider=provider))

    # 2. OpenAI / Ghost
    api_key = _env("OPENAI_API_KEY", "GHOST_API_KEY")
    if api_key:
        base_url = _env("OPENAI_BASE_URL", "GHOST_BASE_URL", default="https://api.openai.com/v1") or ""
        model = _env("OPENAI_MODEL", "GHOST_MODEL", default="gpt-4o-mini") or ""
        if "(" in model:
            model = model.split("(", 1)[0].strip()
        
        provider = ModelCompatibleProvider(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model=model,
            timeout_seconds=60.0,
            name="openai",
            use_json_response_format=False,
        )
        profile = ProviderProfile(
            provider_id="openai-remote",
            model_id=model,
            trust_level=ProviderTrustLevel.TRUSTED_REMOTE,
            capabilities=frozenset({"chat", "tools", "vision"}),
            context_limit=128000,
        )
        registered.append(RegisteredProvider(profile=profile, provider=provider))

    return ProviderRoutingService(
        providers=registered,
        router=ProviderRouter(),
        requirements=requirements or RoutingRequirements(required_capabilities=frozenset({"chat"})),
        audit=audit,
    )