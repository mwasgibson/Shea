from __future__ import annotations

from dataclasses import dataclass, field

from shea.audit.recorder import AuditRecorder
from shea.contracts.models import ModelResponse
from shea.ports.model_provider import ModelProvider

from .exceptions import AllProvidersExhaustedError, NoEligibleProviderError
from .failure import classify_exception
from .health import HealthTracker, ProviderHealthState
from .profile import ProviderProfile
from .requirements import RoutingRequirements
from .router import ProviderRouter


@dataclass
class RegisteredProvider:
    """A live ModelProvider paired with its routing metadata and health
    history. `health` is a mutable HealthTracker even though this
    dataclass isn't frozen — routing outcomes update it in place, the
    same way RecoveryAttempt rows accumulate history rather than being
    replaced.
    """

    profile: ProviderProfile
    provider: ModelProvider
    health: HealthTracker = field(default_factory=HealthTracker)


class ProviderRoutingService:
    """Research doc Section 8's Provider Router, as an integration
    service. Structurally satisfies shea.ports.model_provider.ModelProvider
    (generate/health/capabilities), so it can be passed anywhere a single
    ModelProvider was expected — e.g. directly into
    shea.understanding.IntentParser or shea.planning.PlanningService —
    without either of those knowing routing exists underneath.
    Architecture doc Section 8: "Provider routing sits underneath
    intelligence, not above it."

    `generate()` tries eligible providers in ranked order, recording each
    outcome into that provider's own HealthTracker and auditing every
    attempt. On failure it always considers failover to the next eligible
    provider, regardless of failure category — a different provider may
    not share whatever caused the failure. It does NOT yet retry the same
    provider before failing over (research doc Section 8.14's backoff/
    jitter mechanics), and does not implement gradual traffic recovery
    percentages (Section 8.17) — both are documented simplifications,
    not silent gaps; FailureCategory/RETRYABLE_CATEGORIES exist so a
    future same-provider-retry loop has something correct to consult.
    """

    def __init__(
        self,
        *,
        providers: list[RegisteredProvider],
        router: ProviderRouter,
        requirements: RoutingRequirements,
        audit: AuditRecorder,
        max_provider_attempts: int | None = None,
    ) -> None:
        self._providers = providers
        self._router = router
        self._requirements = requirements
        self._audit = audit
        self._max_attempts = max_provider_attempts

    def generate(self, prompt: str) -> ModelResponse:
        eligible = self._router.eligible(
            [(rp.profile, rp.health.state) for rp in self._providers], self._requirements
        )

        if not eligible:
            self._audit.record(
                actor="provider_routing_service",
                component="provider.router",
                event_type="provider.no_eligible",
                action="generate",
                result="denied",
                metadata={
                    "required_capabilities": sorted(self._requirements.required_capabilities),
                    "require_local_only": self._requirements.require_local_only,
                },
            )
            raise NoEligibleProviderError(
                "no registered provider satisfies the current routing requirements"
            )

        attempt_budget = self._max_attempts or len(eligible)
        attempts: list[tuple[str, str]] = []

        for profile in eligible[:attempt_budget]:
            registered = self._by_id(profile.provider_id)
            try:
                response = registered.provider.generate(prompt)
            except Exception as exc:
                category = classify_exception(exc)
                registered.health.record_failure()
                attempts.append((profile.provider_id, category.value))
                self._audit.record(
                    actor="provider_routing_service",
                    component="provider.router",
                    event_type="provider.attempt_failed",
                    action="generate",
                    result="failed",
                    metadata={"provider_id": profile.provider_id, "category": category.value},
                )
                continue

            registered.health.record_success()
            self._audit.record(
                actor="provider_routing_service",
                component="provider.router",
                event_type="provider.selected",
                action="generate",
                result="success",
                metadata={
                    "provider_id": profile.provider_id,
                    "attempt_number": len(attempts) + 1,
                },
            )
            return response

        self._audit.record(
            actor="provider_routing_service",
            component="provider.router",
            event_type="provider.exhausted",
            action="generate",
            result="failed",
            metadata={"attempts": [{"provider_id": p, "category": c} for p, c in attempts]},
        )
        raise AllProvidersExhaustedError(attempts)

    def health(self) -> bool:
        return any(
            rp.health.state is not ProviderHealthState.UNAVAILABLE for rp in self._providers
        )

    def capabilities(self) -> frozenset[str]:
        """Advisory only: the union of every registered provider's
        capabilities, not a guarantee any single call can use all of
        them — an actual request is still filtered per-provider by
        ProviderRouter.eligible().
        """
        union: set[str] = set()
        for rp in self._providers:
            union |= rp.profile.capabilities
        return frozenset(union)

    def _by_id(self, provider_id: str) -> RegisteredProvider:
        for rp in self._providers:
            if rp.profile.provider_id == provider_id:
                return rp
        raise KeyError(provider_id)