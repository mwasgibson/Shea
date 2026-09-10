from __future__ import annotations

import ssl
from collections.abc import Callable
from http.client import HTTPConnection, HTTPSConnection
from urllib.error import URLError
from urllib.parse import urlparse

from shea.contracts.enums import RiskLevel
from shea.contracts.models import ToolRequest, ToolResponse
from shea.security.exceptions import SecurityViolationError
from shea.security.network_policy import NetworkPolicy
from shea.security.runtime_checks import resolve_and_check_url
from shea.tools.registry import ToolDeclaration, ToolRegistry


class PinnedHTTPSConnection(HTTPSConnection):
    """HTTPS connection that connects to a specific IP but uses a custom hostname for SNI."""

    def __init__(
        self,
        host: str,
        port: int,
        resolved_ip: str,
        sni_hostname: str,
        timeout: float | None = None,
        context: ssl.SSLContext | None = None,
    ) -> None:
        self._resolved_ip = resolved_ip
        self._sni_hostname = sni_hostname
        # Pass the resolved IP as host to parent for connection
        super().__init__(host=resolved_ip, port=port, timeout=timeout, context=context)
        # Override host to be the original hostname for SNI
        self.host = sni_hostname

    def connect(self) -> None:
        """Connect to the resolved IP address with SNI set to the original hostname."""
        # Save the original SNI hostname
        sni_hostname = self.host
        
        # Temporarily set host to resolved IP for connection
        self.host = self._resolved_ip
        
        # Call HTTPConnection.connect to establish the TCP connection
        HTTPConnection.connect(self)
        
        # Restore the SNI hostname
        self.host = sni_hostname
        
        # Get the tunnel host if it exists (from parent class)
        tunnel_host = getattr(self, "_tunnel_host", None)
        if tunnel_host:
            server_hostname = tunnel_host
        else:
            server_hostname = self.host
        
        # Get the SSL context (from parent HTTPSConnection)
        context = getattr(self, "_context", ssl.create_default_context())
        
        # Wrap the socket with SSL using the correct SNI hostname
        self.sock = context.wrap_socket(
            self.sock,
            server_hostname=server_hostname,
        )


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
            resolved = resolve_and_check_url(raw_url, policy, tool="http.fetch")
        except SecurityViolationError as exc:
            return ToolResponse(success=False, error=str(exc))

        try:
            parsed = urlparse(resolved.url)
            is_https = parsed.scheme == "https"

            # Connect directly to the resolved IP address (DNS-pinned)
            # but use the original host for the Host header and TLS SNI
            conn: HTTPConnection | PinnedHTTPSConnection
            if is_https:
                conn = PinnedHTTPSConnection(
                    host=resolved.resolved_ip,
                    port=resolved.port,
                    resolved_ip=resolved.resolved_ip,
                    sni_hostname=resolved.host,
                    timeout=timeout,
                    context=ssl.create_default_context(),
                )
            else:
                conn = HTTPConnection(
                    host=resolved.resolved_ip,
                    port=resolved.port,
                    timeout=timeout,
                )

            # Add Host header with the original hostname (not the resolved IP)
            headers = {"Host": resolved.host}
            if parsed.port and parsed.port not in (80, 443):
                headers["Host"] = f"{resolved.host}:{parsed.port}"

            conn.connect()
            conn.request("GET", parsed.path or "/", headers=headers)
            resp = conn.getresponse()

            body = resp.read(1_000_000)
            charset = resp.headers.get_content_charset() or "utf-8"
            text = body.decode(charset, errors="replace")

            return ToolResponse(
                success=True,
                data={
                    "url": resolved.url,
                    "status": resp.status,
                    "body": text,
                },
            )
        except URLError as exc:
            return ToolResponse(success=False, error=f"Fetch failed: {exc}")
        except ssl.SSLError as exc:
            return ToolResponse(success=False, error=f"SSL failed: {exc}")
        except OSError as exc:
            return ToolResponse(success=False, error=f"Fetch failed: {exc}")
        except Exception as exc:
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
            description="Fetch an HTTP(S) URL with DNS-pinning to prevent DNS rebinding attacks",
            argument_schema=_FETCH_SCHEMA,
        ),
        _fetch_handler(policy),
    )