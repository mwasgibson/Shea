from __future__ import annotations

from collections.abc import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from shea.contracts.enums import RiskLevel
from shea.contracts.models import ToolRequest, ToolResponse
from shea.security.exceptions import SecurityViolationError
from shea.security.network_policy import NetworkPolicy
from shea.security.runtime_checks import resolve_and_check_url
from shea.tools.registry import ToolDeclaration, ToolRegistry

_FETCH_SCHEMA: dict[str, dict[str, object]] = {
    "url": {
        "type": "string",
        "required": True,
        "min_length": 1,
        "pattern": r"^https?://",
        "description": "HTTP(S) URL to fetch",
    },
    "timeout": {
        "type": "integer",
        "required": False,
        "default": 30,
        "min_value": 1,
        "max_value": 120,
        "description": "Request timeout in seconds",
    },
}


def _fetch_handler(policy: NetworkPolicy) -> Callable[[ToolRequest], ToolResponse]:
    def handler(request: ToolRequest) -> ToolResponse:
        raw_url = request.arguments.get("url")
        timeout = request.arguments.get("timeout", 30)
        if not isinstance(raw_url, str):
            return ToolResponse(success=False, error="url must be a string")
        if not isinstance(timeout, int) or isinstance(timeout, bool):
            return ToolResponse(success=False, error="timeout must be an integer")

        try:
            url = resolve_and_check_url(raw_url, policy, tool="http.fetch")
        except SecurityViolationError as exc:
            return ToolResponse(success=False, error=str(exc))

        try:
            req = Request(url, method="GET")
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — URL pre-checked
                body = resp.read(1_000_000)
                charset = resp.headers.get_content_charset() or "utf-8"
                text = body.decode(charset, errors="replace")
                return ToolResponse(
                    success=True,
                    data={
                        "url": url,
                        "status": getattr(resp, "status", 200),
                        "body": text,
                    },
                )
        except URLError as exc:
            return ToolResponse(success=False, error=f"Fetch failed: {exc}")
        except OSError as exc:
            return ToolResponse(success=False, error=f"Fetch failed: {exc}")

    return handler


def register_http_fetch_tool(registry: ToolRegistry, policy: NetworkPolicy) -> None:
    registry.register(
        ToolDeclaration(
            name="http.fetch",
            capabilities=frozenset({"network.connect"}),
            baseline_risk=RiskLevel.MEDIUM,
            isolation_required=True,
            audit_required=True,
            description="Fetch an HTTP(S) URL after DNS re-check against network policy",
            argument_schema=_FETCH_SCHEMA,
        ),
        _fetch_handler(policy),
    )