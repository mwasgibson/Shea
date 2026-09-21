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

    # 2. Ghost (OpenRouter)
    ghost_key = _env("GHOST_API_KEY")
    if ghost_key:
        base_url = _env("GHOST_BASE_URL", default="https://openrouter.ai/api/v1") or "https://openrouter.ai/api/v1"
        model = _env("GHOST_MODEL", default="meta-llama/llama-3.1-8b-instruct") or "meta-llama/llama-3.1-8b-instruct"
        provider = ModelCompatibleProvider(
            api_key=ghost_key,
            base_url=base_url.rstrip("/"),
            model=model,
            timeout_seconds=60.0,
            name="openrouter",
            use_json_response_format=False,
        )
        profile = ProviderProfile(
            provider_id="openrouter-remote",
            model_id=model,
            trust_level=ProviderTrustLevel.TRUSTED_REMOTE,
            capabilities=frozenset({"chat", "tools", "vision"}),
            context_limit=128000,
        )
        registered.append(RegisteredProvider(profile=profile, provider=provider))

    # 3. OpenAI (Nvidia)
    openai_key = _env("OPENAI_API_KEY")
    if openai_key:
        base_url = _env("OPENAI_BASE_URL", default="https://integrate.api.nvidia.com/v1") or "https://integrate.api.nvidia.com/v1"
        model = _env("OPENAI_MODEL", default="nvidia/nemotron-3.5-lightning-30b-a3b") or "nvidia/nemotron-3.5-lightning-30b-a3b"
        provider = ModelCompatibleProvider(
            api_key=openai_key,
            base_url=base_url.rstrip("/"),
            model=model,
            timeout_seconds=60.0,
            name="nvidia",
            use_json_response_format=False,
        )
        profile = ProviderProfile(
            provider_id="nvidia-remote",
            model_id=model,
            trust_level=ProviderTrustLevel.TRUSTED_REMOTE,
            capabilities=frozenset({"chat", "tools"}),
            context_limit=128000,
        )
        registered.append(RegisteredProvider(profile=profile, provider=provider))

    # 4. Anthropic (Kimi)
    anthropic_key = _env("ANTHROPIC_AUTH_TOKEN")
    if anthropic_key:
        base_url = _env("ANTHROPIC_BASE_URL", default="https://api.moonshot.cn/v1") or "https://api.moonshot.cn/v1"
        model = _env("ANTHROPIC_MODEL", default="moonshot-v1-8k") or "moonshot-v1-8k"
        provider = ModelCompatibleProvider(
            api_key=anthropic_key,
            base_url=base_url.rstrip("/"),
            model=model,
            timeout_seconds=60.0,
            name="kimi",
            use_json_response_format=False,
        )
        profile = ProviderProfile(
            provider_id="kimi-remote",
            model_id=model,
            trust_level=ProviderTrustLevel.TRUSTED_REMOTE,
            capabilities=frozenset({"chat", "tools"}),
            context_limit=128000,
        )
        registered.append(RegisteredProvider(profile=profile, provider=provider))

    return ProviderRoutingService(
        providers=registered,
        router=ProviderRouter(),
        requirements=requirements or RoutingRequirements(required_capabilities=frozenset({"chat"})),
        audit=audit,
    )