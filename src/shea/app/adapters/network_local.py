from __future__ import annotations

import ssl
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlparse

from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome
from shea.app.ports.process import AdapterContext
from shea.security.exceptions import SecurityViolationError
from shea.security.network_policy import NetworkPolicy
from shea.security.runtime_checks import resolve_and_check_url


class PinnedHTTPSConnection(HTTPSConnection):
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
        super().__init__(host=resolved_ip, port=port, timeout=timeout, context=context)
        self.host = sni_hostname

    def connect(self) -> None:
        sni = self.host
        self.host = self._resolved_ip
        HTTPConnection.connect(self)
        self.host = sni
        context = getattr(self, "_context", None) or ssl.create_default_context()
        self.sock = context.wrap_socket(self.sock, server_hostname=sni)


class LocalNetworkAdapter:
    """V1 network adapter: DNS re-check, private-IP block, pinned connect."""

    name = "network.local"

    def __init__(self, policy: NetworkPolicy | None = None) -> None:
        self._default_policy = policy or NetworkPolicy()

    def supports(self, contract: ExecutionContract) -> bool:
        return contract.operation.startswith("network.") or contract.capability in {
            "network.connect",
            "network.request",
        }

    def invoke(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        raw_ctx = contract.metadata.get("_adapter_context")
        ctx: AdapterContext | None = (
            raw_ctx if isinstance(raw_ctx, AdapterContext) else None
        )
        if ctx is None:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="network.local requires scope + AdapterContext",
                evidence=self._base(receipt, attempt),
            )

        net = ctx.scope.network
        policy = NetworkPolicy(
            allowed_hosts=net.allowed_hosts,
            block_private_networks=net.block_private,
        )
        # If scope has no allowlist, fall back to adapter default (still fail-closed on private)
        if net.allowed_hosts is None and self._default_policy.allowed_hosts is not None:
            policy = NetworkPolicy(
                allowed_hosts=self._default_policy.allowed_hosts,
                blocked_hostnames=self._default_policy.blocked_hostnames,
                block_private_networks=net.block_private,
            )

        url = contract.arguments.get("url") or contract.target
        if not isinstance(url, str) or not url.strip():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="url must be a non-empty str (arguments.url or target)",
                evidence=self._base(receipt, attempt),
            )

        method = str(contract.arguments.get("method", "GET")).upper()
        if method not in {"GET", "HEAD"}:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="V1 network.local only allows GET/HEAD",
                evidence=self._base(receipt, attempt),
            )

        max_bytes = 1_000_000
        if ctx.scope.resources.output_bytes is not None:
            max_bytes = ctx.scope.resources.output_bytes

        timeout_s = 30.0
        if ctx.scope.resources.wall_time_ms is not None:
            timeout_s = ctx.scope.resources.wall_time_ms / 1000.0

        try:
            resolved = resolve_and_check_url(url, policy, tool="network.local")
        except SecurityViolationError as exc:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=str(exc),
                evidence={**self._base(receipt, attempt), "url": url},
            )

        parsed = urlparse(url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        max_redirects = int(contract.arguments.get("max_redirects", 3))
        if max_redirects < 0 or max_redirects > 5:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="max_redirects must be 0..5",
                evidence=self._base(receipt, attempt),
            )

        current_url = url
        hop = 0
        status = 0
        body = b""
        truncated = False
        chain: list[str] = [current_url]

        try:
            while True:
                try:
                    resolved = resolve_and_check_url(
                        current_url, policy, tool="network.local"
                    )
                except SecurityViolationError as exc:
                    return AdapterResult(
                        outcome=AppOutcome.FAILURE,
                        error=str(exc),
                        evidence={
                            **self._base(receipt, attempt),
                            "url": url,
                            "failed_url": current_url,
                            "redirect_chain": chain,
                        },
                    )

                parsed = urlparse(current_url)
                path = parsed.path or "/"
                if parsed.query:
                    path = f"{path}?{parsed.query}"

                if parsed.scheme == "https":
                    conn = PinnedHTTPSConnection(
                        host=resolved.host,
                        port=resolved.port,
                        resolved_ip=resolved.resolved_ip,
                        sni_hostname=resolved.host,
                        timeout=timeout_s,
                    )
                elif parsed.scheme == "http":
                    conn = HTTPConnection(
                        host=resolved.resolved_ip,
                        port=resolved.port,
                        timeout=timeout_s,
                    )
                else:
                    return AdapterResult(
                        outcome=AppOutcome.FAILURE,
                        error=f"unsupported scheme: {parsed.scheme!r}",
                        evidence={**self._base(receipt, attempt), "url": current_url},
                    )

                headers = {
                    "Host": resolved.host,
                    "User-Agent": "shea-network.local/1",
                }
                conn.request(method if hop == 0 else "GET", path, headers=headers)
                response = conn.getresponse()
                status = response.status
                location = response.getheader("Location")
                body = response.read(max_bytes + 1)
                truncated = len(body) > max_bytes
                body = body[:max_bytes]
                conn.close()

                if status in {301, 302, 303, 307, 308} and location and hop < max_redirects:
                    # Resolve relative Location against current_url
                    from urllib.parse import urljoin

                    next_url = urljoin(current_url, location)
                    chain.append(next_url)
                    current_url = next_url
                    hop += 1
                    method = "GET" if status in {301, 302, 303} else method
                    continue
                break
        except OSError as exc:
            return AdapterResult(
                outcome=AppOutcome.UNKNOWN,
                error=f"network error: {exc}",
                evidence={
                    **self._base(receipt, attempt),
                    "url": url,
                    "redirect_chain": chain,
                },
            )

        text = body.decode("utf-8", errors="replace")
        outcome = AppOutcome.SUCCESS if 200 <= status < 300 else AppOutcome.FAILURE
        return AdapterResult(
            outcome=outcome,
            error=None if outcome is AppOutcome.SUCCESS else f"HTTP {status}",
            evidence={
                **self._base(receipt, attempt),
                "url": url,
                "final_url": current_url,
                "status": status,
                "method": method,
                "redirect_hops": hop,
                "redirect_chain": chain,
                "body_preview": text[:2000],
                "bytes_read": len(body),
                "truncated": truncated,
                "postcondition": "response_received",
            },
        )

    def _base(
        self, receipt: ExecutionReceipt, attempt: ExecutionAttempt
    ) -> dict[str, str]:
        return {"receipt_id": receipt.id, "attempt_id": attempt.id}