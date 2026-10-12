from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shea.model.exceptions import ModelUnavailableError
from shea.model.model_compatible import ModelCompatibleProvider


def test_generate_parses_structured_plan() -> None:
    provider = ModelCompatibleProvider(api_key="test-key", model="test-model")
    body: dict[str, Any] = {
        "id": "chatcmpl-1",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "steps": [
                                {
                                    "tool": "filesystem.read",
                                    "action": "read",
                                    "arguments": {"path": "/tmp/x"},
                                }
                            ]
                        }
                    )
                },
            }
        ],
    }
    raw = json.dumps(body).encode()

    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = provider.generate("Goal: read a file")

    assert result.structured_data is not None
    assert result.structured_data["steps"][0]["tool"] == "filesystem.read"
    assert provider.health() is True


def test_generate_http_error_marks_unhealthy() -> None:
    import urllib.error

    provider = ModelCompatibleProvider(api_key="test-key")
    err = urllib.error.HTTPError(
        url="https://example.com",
        code=401,
        msg="Unauthorized",
        hdrs=None,  # type: ignore[arg-type]
        fp=MagicMock(read=lambda: b"nope"),
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(ModelUnavailableError):
            provider.generate("x")
    assert provider.health() is False


def test_generate_can_disable_json_response_format() -> None:
    provider = ModelCompatibleProvider(
        api_key="test-key",
        use_json_response_format=False,
    )
    body: dict[str, Any] = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": '{"steps": []}'},
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(body).encode()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp) as urlopen:
        provider.generate("Goal: do something")

    request = urlopen.call_args.args[0]
    request_body = json.loads(request.data)
    assert "response_format" not in request_body

# --- Realistic model output shapes for the combined classify+answer prompt ---
# The prompt contains the word "json", so the adapter's JSON extraction runs.
# Each case is something a real (especially small, local) model actually
# emits. Ollama runs with use_json_response_format=False, so nothing forces
# valid JSON on the model's side.

COMBINED_PROMPT = "Reply with a single JSON object only. User request: hi"


def _generate_with_content(content: str) -> Any:
    provider = ModelCompatibleProvider(api_key="k", use_json_response_format=False)
    body = {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
    resp = MagicMock()
    resp.read.return_value = json.dumps(body).encode()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = None
    with patch("urllib.request.urlopen", return_value=resp):
        return provider.generate(COMBINED_PROMPT)


def test_reply_containing_a_code_block_is_not_hijacked_by_the_fence_regex() -> None:
    reply = "Here you go:\n```python\nprint('hi')\n```\nHope that helps."
    content = json.dumps({"type": "query", "goal": "g", "confidence": 1.0, "reply": reply})
    result = _generate_with_content(content)
    assert result.structured_data is not None
    assert result.structured_data["reply"] == reply


def test_literal_newlines_inside_the_reply_string_still_parse() -> None:
    content = (
        '{"type": "query", "goal": "g", "confidence": 1.0, '
        '"reply": "First paragraph.\n\nSecond paragraph."}'
    )
    result = _generate_with_content(content)
    assert result.structured_data is not None
    assert result.structured_data["reply"] == "First paragraph.\n\nSecond paragraph."


def test_json_wrapped_in_a_json_fence_parses() -> None:
    content = '```json\n{"type": "query", "goal": "g", "confidence": 1.0, "reply": "hi"}\n```'
    result = _generate_with_content(content)
    assert result.structured_data is not None
    assert result.structured_data["reply"] == "hi"


def test_prose_before_the_json_becomes_thinking_and_does_not_break_parsing() -> None:
    content = 'Let me classify this.\n{"type": "query", "goal": "g", "confidence": 1.0, "reply": "hi"}'
    result = _generate_with_content(content)
    assert result.structured_data is not None
    assert result.metadata["thinking"] == "Let me classify this."


def test_trailing_commentary_after_the_json_is_ignored() -> None:
    content = (
        '{"type": "query", "goal": "g", "confidence": 1.0, "reply": "a {b} c"}\n'
        "Note: I answered directly. {not json}"
    )
    result = _generate_with_content(content)
    assert result.structured_data is not None
    assert result.structured_data["reply"] == "a {b} c"


def test_think_block_is_still_extracted_before_parsing() -> None:
    content = (
        "<think>user is greeting</think>"
        '{"type": "query", "goal": "g", "confidence": 1.0, "reply": "hi"}'
    )
    result = _generate_with_content(content)
    assert result.structured_data is not None
    assert result.metadata["thinking"] == "user is greeting"


def test_unparseable_output_yields_no_structured_data() -> None:
    result = _generate_with_content("Sure! Happy to help with that.")
    assert result.structured_data is None
