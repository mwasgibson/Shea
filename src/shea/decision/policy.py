from __future__ import annotations

from dataclasses import dataclass, field

from shea.contracts.enums import PolicyVerdict

# Vocabulary taken directly from technical doc Section 10.4's tool
# capability examples. Kept here as defaults, not gospel — a real
# deployment configures its own deny/authorization sets; PolicyEngine
# itself contains no domain-specific logic, only the evaluation rule.
DEFAULT_DENY_CAPABILITIES: frozenset[str] = frozenset()

DEFAULT_AUTHORIZATION_REQUIRED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "filesystem.write",
        "process.execute",
        "network.connect",
        "network.listen",
        "system.configure",
        "credential.access",
        "credential.modify",
        "data.modify",
        "data.exfiltrate",
        "data.delete",
        "data.encrypt",
        "data.decrypt",
        "data.sign",
        "certificate.sign",
        "certificate.install",
        "certificate.modify",
    }
)


@dataclass(frozen=True)
class PolicyEngine:
    """Deterministic, data-driven capability policy — technical doc
    Component: Policy Engine ("Evaluates deterministic rules and
    constraints").

    This is intentionally the simplest possible rule: a capability set
    intersecting `deny_capabilities` is an absolute, non-negotiable block
    (research doc Section 15.12's "system integrity invariant"); one
    intersecting `authorization_required_capabilities` needs a human
    decision but CAN proceed with one. Anything else is unconditionally
    allowed. Determinism matters here specifically because Section 15.27
    requires policy decisions to not depend on model output or randomness.
    """

    deny_capabilities: frozenset[str] = field(default_factory=lambda: DEFAULT_DENY_CAPABILITIES)
    authorization_required_capabilities: frozenset[str] = field(
        default_factory=lambda: DEFAULT_AUTHORIZATION_REQUIRED_CAPABILITIES
    )

    def evaluate(self, capabilities: frozenset[str]) -> PolicyVerdict:
        if capabilities & self.deny_capabilities:
            return PolicyVerdict.DENIED
        if capabilities & self.authorization_required_capabilities:
            return PolicyVerdict.REQUIRES_AUTHORIZATION
        return PolicyVerdict.ALLOWED