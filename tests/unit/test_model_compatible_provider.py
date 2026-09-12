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