from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, cast

from shea.contracts.models import ModelResponse
from shea.model.exceptions import MalformedModelOutputError, ModelUnavailableError

DEFAULT_CAPABILITIES: frozenset[str] = frozenset({"structured_output", "chat"})


@dataclass
class ModelCompatibleProvider:
    """HTTP chat-completions provider (OpenAI API shape).

    Works with OpenAI, Azure OpenAI-compatible gateways, and local servers
    that expose ``POST {base_url}/chat/completions``.

    Not authority: Planning still validates steps against the tool registry.
    """

    api_key: str
    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 60.0
    name: str = "openai_compatible"
    use_json_response_format: bool = True
    capabilities_set: frozenset[str] = field(default_factory=lambda: DEFAULT_CAPABILITIES)
    _healthy: bool = True

    def health(self) -> bool:
        return self._healthy

    def capabilities(self) -> frozenset[str]:
        return self.capabilities_set

    def generate(self, prompt: str) -> ModelResponse:
        url = self.base_url.rstrip("/") + "/chat/completions"
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a planner for the Shea agent. "
                        "Reply with a single JSON object only, shape: "
                        '{"steps":[{"tool":str,"action":str,"arguments":{},"description":str}]}. '
                        "Use only tools the user context implies; prefer filesystem.read, "
                        "filesystem.write when appropriate. Empty steps are invalid."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        if self.use_json_response_format:
            body["response_format"] = {"type": "json_object"}
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            self._healthy = False
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ModelUnavailableError(self.name) from RuntimeError(
                f"HTTP {exc.code}: {detail}"
            )
        except urllib.error.URLError as exc:
            self._healthy = False
            raise ModelUnavailableError(self.name) from exc

        self._healthy = True

        # Handle SSE / text/event-stream if the gateway forces streaming
        if "text/event-stream" in content_type or raw.lstrip().startswith("data:"):
            content_pieces: list[str] = []
            model_id: str | None = None
            finish_reason: str = "stop"

            for line in raw.splitlines():
                line = line.strip()
                if not line.startswith("data:") or line == "data: [DONE]":
                    continue
                chunk_str = line[len("data:") :].strip()
                try:
                    chunk = json.loads(chunk_str)
                except json.JSONDecodeError:
                    continue

                if "id" in chunk:
                    model_id = chunk["id"]
                choices = chunk.get("choices", [])
                if choices:
                    choice = choices[0]
                    delta = choice.get("delta", {})
                    if "content" in delta and delta["content"]:
                        content_pieces.append(delta["content"])
                    if choice.get("finish_reason"):
                        finish_reason = str(choice["finish_reason"])

            content = "".join(content_pieces)
            response_id = model_id
        else:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise MalformedModelOutputError(
                    "provider returned non-JSON body"
                ) from exc

            try:
                content = payload["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise MalformedModelOutputError(
                    "provider response missing choices[0].message.content"
                ) from exc

            finish_reason = str(
                payload.get("choices", [{}])[0].get("finish_reason") or "stop"
            )
            response_id = payload.get("id")

        if not isinstance(content, str):
            raise MalformedModelOutputError("message content must be str")

        # Strip markdown fences if the model wrapped the JSON in ```json ... ```
        clean_content = content.strip()
        if clean_content.startswith("```"):
            clean_content = clean_content.strip("`")
            if clean_content.startswith("json"):
                clean_content = clean_content[4:].strip()

        try:
            parsed = json.loads(clean_content)
            structured = (
                cast(dict[str, Any], parsed) if isinstance(parsed, dict) else None
            )
        except json.JSONDecodeError:
            structured = None

        if structured is None:
            raise MalformedModelOutputError(
                f"model content was not a JSON object: {content!r}"
            )

        return ModelResponse(
            content=content,
            structured_data=structured,
            finish_reason=finish_reason,
            metadata={
                "provider": self.name,
                "model": self.model,
                "id": response_id,
            },
        )