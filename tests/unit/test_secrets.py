from __future__ import annotations

from typing import Any

from shea.security.secrets import REDACTED, SecretRedactor


def test_redacts_aws_access_key() -> None:
    redactor = SecretRedactor()
    result = redactor.redact("my key is AKIAABCDEFGHIJKLMNOP, keep it safe")
    assert "AKIAABCDEFGHIJKLMNOP" not in result
    assert REDACTED in result


def test_redacts_sk_style_api_key() -> None:
    redactor = SecretRedactor()
    result = redactor.redact("Authorization uses sk-abcdefghijklmnopqrstuvwx")
    assert "sk-abcdefghijklmnopqrstuvwx" not in result


def test_redacts_bearer_token() -> None:
    redactor = SecretRedactor()
    result = redactor.redact("Authorization: Bearer abc123.def456-ghi789")
    assert "abc123.def456-ghi789" not in result


def test_redacts_key_value_pairs() -> None:
    redactor = SecretRedactor()
    result = redactor.redact("password=hunter2andmore")
    assert "hunter2andmore" not in result


def test_leaves_ordinary_text_unchanged() -> None:
    redactor = SecretRedactor()
    text = "the weather today is sunny with a light breeze"
    assert redactor.redact(text) == text


def test_redact_mapping_handles_nested_dicts_and_lists() -> None:
    redactor = SecretRedactor()
    data: dict[str, Any] = {
        "top": "AKIAABCDEFGHIJKLMNOP",
        "nested": {"inner": "sk-abcdefghijklmnopqrstuvwx"},
        "list": ["fine", "AKIAABCDEFGHIJKLMNOP"],
        "number": 42,
    }

    redacted = redactor.redact_mapping(data)

    assert "AKIAABCDEFGHIJKLMNOP" not in redacted["top"]
    assert "sk-abcdefghijklmnopqrstuvwx" not in redacted["nested"]["inner"]
    assert "AKIAABCDEFGHIJKLMNOP" not in redacted["list"][1]
    assert redacted["list"][0] == "fine"
    assert redacted["number"] == 42


def test_redact_mapping_does_not_mutate_original() -> None:
    redactor = SecretRedactor()
    data = {"key": "AKIAABCDEFGHIJKLMNOP"}

    redactor.redact_mapping(data)

    assert data["key"] == "AKIAABCDEFGHIJKLMNOP"