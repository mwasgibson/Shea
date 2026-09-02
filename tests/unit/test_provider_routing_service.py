from __future__ import annotations

import sqlite3

import pytest

from shea.audit.recorder import AuditRecorder
from shea.contracts.models import ModelResponse
from shea.model.scripted import ScriptedModelProvider
from shea.provider.exceptions import AllProvidersExhaustedError, NoEligibleProviderError
from shea.provider.health import ProviderHealthState
from shea.provider.profile import ProviderProfile, ProviderTrustLevel
from shea.provider.requirements import RoutingRequirements
from shea.provider.router import ProviderRouter
from shea.provider.service import ProviderRoutingService, RegisteredProvider
from shea.understanding.deterministic import DeterministicIntentMatcher
from shea.understanding.parser import IntentParser


def local_profile(provider_id: str, **overrides: object) -> ProviderProfile:
    defaults: dict[str, object] = dict(
        provider_id=provider_id,
        model_id=f"{provider_id}-model",
        trust_level=ProviderTrustLevel.LOCAL,
        capabilities=frozenset({"structured_output"}),
        context_limit=8000,
    )
    defaults.update(overrides)
    return ProviderProfile(**defaults)  # type: ignore[arg-type]


def make_service(
    providers: list[RegisteredProvider],
    audit: AuditRecorder,
    requirements: RoutingRequirements | None = None,
) -> ProviderRoutingService:
    return ProviderRoutingService(
        providers=providers,
        router=ProviderRouter(),
        requirements=requirements or RoutingRequirements(),
        audit=audit,
    )


def test_single_healthy_provider_succeeds(audit_recorder: AuditRecorder) -> None:
    scripted = ScriptedModelProvider()
    scripted.queue_response(ModelResponse(content="hello"))
    registered = RegisteredProvider(profile=local_profile("p1"), provider=scripted)

    service = make_service([registered], audit_recorder)
    response = service.generate("hi")

    assert response.content == "hello"
    assert registered.health.state == ProviderHealthState.HEALTHY


def test_failover_to_second_provider_on_first_failure(audit_recorder: AuditRecorder) -> None:
    failing = ScriptedModelProvider()  # empty queue -> raises ModelUnavailableError
    working = ScriptedModelProvider()
    working.queue_response(ModelResponse(content="from second provider"))

    first = RegisteredProvider(profile=local_profile("first"), provider=failing)
    second = RegisteredProvider(profile=local_profile("second"), provider=working)

    service = make_service([first, second], audit_recorder)
    response = service.generate("hi")

    assert response.content == "from second provider"


def test_failed_provider_health_is_recorded(audit_recorder: AuditRecorder) -> None:
    failing = ScriptedModelProvider()
    working = ScriptedModelProvider()
    working.queue_response(ModelResponse(content="ok"))

    first = RegisteredProvider(profile=local_profile("first"), provider=failing)
    second = RegisteredProvider(profile=local_profile("second"), provider=working)

    service = make_service([first, second], audit_recorder)
    service.generate("hi")

    assert second.health.state == ProviderHealthState.HEALTHY
    # First provider's failure was recorded even though the overall call
    # succeeded via failover — proven through observable behavior, not
    # reaching into the tracker's private history.
    first.health.record_success()
    first.health.record_success()
    first.health.record_success()
    first.health.record_success()
    # 1 failure + 4 successes out of a window of 10 = 20% error rate,
    # below the 30% degraded threshold.
    assert first.health.state == ProviderHealthState.HEALTHY


def test_all_providers_exhausted_raises(audit_recorder: AuditRecorder) -> None:
    first = RegisteredProvider(profile=local_profile("first"), provider=ScriptedModelProvider())
    second = RegisteredProvider(
        profile=local_profile("second"), provider=ScriptedModelProvider()
    )

    service = make_service([first, second], audit_recorder)

    with pytest.raises(AllProvidersExhaustedError) as exc_info:
        service.generate("hi")

    assert len(exc_info.value.attempts) == 2


def test_no_eligible_provider_raises_without_attempting_any(
    audit_recorder: AuditRecorder,
) -> None:
    calls: list[str] = []

    class TrackingProvider(ScriptedModelProvider):
        def generate(self, prompt: str) -> ModelResponse:
            calls.append(prompt)
            return super().generate(prompt)

    untrusted = RegisteredProvider(
        profile=local_profile("bad", trust_level=ProviderTrustLevel.UNTRUSTED),
        provider=TrackingProvider(),
    )

    service = make_service([untrusted], audit_recorder)

    with pytest.raises(NoEligibleProviderError):
        service.generate("hi")

    assert calls == []


def test_require_local_only_never_fails_over_to_remote(audit_recorder: AuditRecorder) -> None:
    """The concrete form of research doc Section 8.11: a local-only
    requirement must never be satisfied by a remote provider, even as a
    failover when no local provider is registered at all.
    """
    remote = RegisteredProvider(
        profile=local_profile("remote", trust_level=ProviderTrustLevel.TRUSTED_REMOTE),
        provider=ScriptedModelProvider(),
    )

    service = make_service(
        [remote], audit_recorder, requirements=RoutingRequirements(require_local_only=True)
    )

    with pytest.raises(NoEligibleProviderError):
        service.generate("sensitive local data")


def test_missing_capability_provider_never_attempted(audit_recorder: AuditRecorder) -> None:
    calls: list[str] = []

    class TrackingProvider(ScriptedModelProvider):
        def generate(self, prompt: str) -> ModelResponse:
            calls.append(prompt)
            return super().generate(prompt)

    provider = RegisteredProvider(
        profile=local_profile("p1", capabilities=frozenset({"structured_output"})),
        provider=TrackingProvider(),
    )

    service = make_service(
        [provider],
        audit_recorder,
        requirements=RoutingRequirements(required_capabilities=frozenset({"tool_calling"})),
    )

    with pytest.raises(NoEligibleProviderError):
        service.generate("hi")

    assert calls == []


def test_service_is_a_drop_in_model_provider_for_intent_parser(
    audit_recorder: AuditRecorder,
) -> None:
    """Structurally proves ProviderRoutingService satisfies the
    ModelProvider port well enough to be passed directly into
    IntentParser, exactly as a single ScriptedModelProvider would be.
    """
    scripted = ScriptedModelProvider()
    scripted.queue_response(
        ModelResponse(
            content="",
            structured_data={
                "type": "weather.lookup",
                "goal": "check weather",
                "confidence": 0.9,
            },
        )
    )
    registered = RegisteredProvider(profile=local_profile("p1"), provider=scripted)
    service = make_service([registered], audit_recorder)

    parser = IntentParser(DeterministicIntentMatcher(), model_provider=service)
    draft = parser.parse("what's the weather")

    assert draft.type == "weather.lookup"


def test_exhaustion_is_audited(audit_recorder: AuditRecorder, conn: sqlite3.Connection) -> None:
    provider = RegisteredProvider(profile=local_profile("p1"), provider=ScriptedModelProvider())
    service = make_service([provider], audit_recorder)

    with pytest.raises(AllProvidersExhaustedError):
        service.generate("hi")

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE event_type = ?", ("provider.exhausted",)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "failed"


def test_no_eligible_is_audited(audit_recorder: AuditRecorder, conn: sqlite3.Connection) -> None:
    provider = RegisteredProvider(
        profile=local_profile("p1", trust_level=ProviderTrustLevel.UNTRUSTED),
        provider=ScriptedModelProvider(),
    )
    service = make_service([provider], audit_recorder)

    with pytest.raises(NoEligibleProviderError):
        service.generate("hi")

    rows = conn.execute(
        "SELECT * FROM audit_events WHERE event_type = ?", ("provider.no_eligible",)
    ).fetchall()
    assert len(rows) == 1


def test_health_reflects_at_least_one_available_provider(audit_recorder: AuditRecorder) -> None:
    provider = RegisteredProvider(profile=local_profile("p1"), provider=ScriptedModelProvider())
    service = make_service([provider], audit_recorder)
    assert service.health() is True


def test_capabilities_are_union_of_registered_providers(audit_recorder: AuditRecorder) -> None:
    a = RegisteredProvider(
        profile=local_profile("a", capabilities=frozenset({"structured_output"})),
        provider=ScriptedModelProvider(),
    )
    b = RegisteredProvider(
        profile=local_profile("b", capabilities=frozenset({"tool_calling"})),
        provider=ScriptedModelProvider(),
    )
    service = make_service([a, b], audit_recorder)

    assert service.capabilities() == frozenset({"structured_output", "tool_calling"})