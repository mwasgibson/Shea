from __future__ import annotations

from shea.model.exceptions import MalformedModelOutputError, ModelUnavailableError
from shea.provider.failure import RETRYABLE_CATEGORIES, FailureCategory, classify_exception


def test_model_unavailable_error_classified_as_provider_unavailable() -> None:
    category = classify_exception(ModelUnavailableError("scripted"))
    assert category == FailureCategory.PROVIDER_UNAVAILABLE


def test_malformed_model_output_error_classified_as_malformed_response() -> None:
    category = classify_exception(MalformedModelOutputError("bad json"))
    assert category == FailureCategory.MALFORMED_RESPONSE


def test_unrecognized_exception_classified_as_unknown() -> None:
    category = classify_exception(ValueError("something else entirely"))
    assert category == FailureCategory.UNKNOWN


def test_provider_unavailable_is_retryable() -> None:
    assert FailureCategory.PROVIDER_UNAVAILABLE in RETRYABLE_CATEGORIES


def test_malformed_response_is_not_retryable() -> None:
    assert FailureCategory.MALFORMED_RESPONSE not in RETRYABLE_CATEGORIES


def test_auth_failure_is_not_retryable() -> None:
    assert FailureCategory.AUTH_FAILURE not in RETRYABLE_CATEGORIES


def test_unknown_is_retryable() -> None:
    assert FailureCategory.UNKNOWN in RETRYABLE_CATEGORIES