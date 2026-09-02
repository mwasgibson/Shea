from __future__ import annotations

from enum import StrEnum

from shea.model.exceptions import MalformedModelOutputError, ModelUnavailableError


class FailureCategory(StrEnum):
    """Research doc Section 8.10's exact taxonomy."""

    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_FAILURE = "AUTH_FAILURE"
    SERVER_ERROR = "SERVER_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    CAPABILITY_FAILURE = "CAPABILITY_FAILURE"
    POLICY_FAILURE = "POLICY_FAILURE"
    CONTEXT_TOO_LARGE = "CONTEXT_TOO_LARGE"
    CONTENT_REJECTION = "CONTENT_REJECTION"
    UNKNOWN = "UNKNOWN"


# Whether retrying the SAME provider again is worth attempting. This does
# NOT govern whether failover to a DIFFERENT eligible provider is allowed
# — ProviderRoutingService always considers failover regardless of
# category, since a different provider may not share whatever caused a
# non-retryable failure on this one. It governs only same-provider retry,
# which this phase does not yet implement (see ProviderRoutingService's
# docstring) — the categorization is captured now so that mechanism has
# something correct to consult when it's built.
RETRYABLE_CATEGORIES: frozenset[FailureCategory] = frozenset(
    {
        FailureCategory.PROVIDER_TIMEOUT,
        FailureCategory.PROVIDER_UNAVAILABLE,
        FailureCategory.RATE_LIMITED,
        FailureCategory.SERVER_ERROR,
        FailureCategory.NETWORK_ERROR,
        FailureCategory.UNKNOWN,
    }
)


def classify_exception(exc: Exception) -> FailureCategory:
    """Maps known exception types to a FailureCategory.

    Extension point: a real ModelProvider adapter (OpenAI, Anthropic, a
    local model server) should raise or translate its own errors into
    recognizable types here as they're integrated — an HTTP 429 becomes
    RATE_LIMITED, a connection error becomes NETWORK_ERROR, and so on.
    Until then, anything not explicitly recognized is UNKNOWN, which is
    itself meaningful (retryable, per RETRYABLE_CATEGORIES) rather than a
    silent default that hides the gap.
    """
    if isinstance(exc, ModelUnavailableError):
        return FailureCategory.PROVIDER_UNAVAILABLE
    if isinstance(exc, MalformedModelOutputError):
        return FailureCategory.MALFORMED_RESPONSE
    return FailureCategory.UNKNOWN