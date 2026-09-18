from __future__ import annotations

import platform
from typing import Any

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


def playwright_available() -> bool:
    """True only if the package imports *and* this OS is a known-supported host.

    Shea must run on older macOS/Linux without modern browser binaries.
    Unsupported hosts fall through to browser.local (stdlib HTTP document mode).
    """
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False

    system = platform.system()
    if system == "Darwin":
        ver = platform.mac_ver()[0] or "0"
        try:
            major = int(ver.split(".")[0])
        except ValueError:
            return False
        # WebKit and modern Playwright engine builds generally require macOS 13+ / 14+.
        if major < 13:
            return False
        return True

    if system in {"Windows", "Linux"}:
        return True

    return False


class PlaywrightBrowserAdapter:
    """EP browser engine: isolated context across Chromium, Firefox, or WebKit.

    Tries available open-source browser binaries in sequence:
    Chromium -> Firefox -> WebKit.
    Requires optional extra: pip install -e '.[browser]' && playwright install
    URL still passes resolve_and_check_url under NetworkScope (SSRF fail-closed).
    """

    name = "browser.engine"

    def supports(self, contract: ExecutionContract) -> bool:
        if not playwright_available():
            return False
        return contract.operation.startswith("browser.") or contract.capability in {
            "browser.navigate",
            "browser.read",
            "browser.engine",
        }

    def _launch_browser(self, p: Any) -> tuple[Any, str]:
        """Attempt to launch an available open-source engine in preference order."""
        engines = [
            ("chromium", p.chromium),
            ("firefox", p.firefox),
            ("webkit", p.webkit),
        ]
        errors: list[str] = []

        for name, engine in engines:
            try:
                browser = engine.launch(headless=True)
                return browser, name
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")

        raise RuntimeError(
            "no supported browser binary found (tried chromium, firefox, webkit). "
            f"Run 'playwright install'. Details: {'; '.join(errors)}"
        )

    def invoke(
        self,
        contract: ExecutionContract,
        receipt: ExecutionReceipt,
        attempt: ExecutionAttempt,
    ) -> AdapterResult:
        raw_ctx = contract.metadata.get("_adapter_context")
        if not isinstance(raw_ctx, AdapterContext):
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="browser.engine requires scope + AdapterContext",
                evidence=self._base(receipt, attempt),
            )

        if not playwright_available():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="playwright not installed (pip install -e '.[browser]')",
                evidence=self._base(receipt, attempt),
            )

        url = contract.arguments.get("url") or contract.target
        if not isinstance(url, str) or not url.strip():
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="url must be non-empty str",
                evidence=self._base(receipt, attempt),
            )

        net = raw_ctx.scope.network
        policy = NetworkPolicy(
            allowed_hosts=net.allowed_hosts,
            block_private_networks=net.block_private,
        )
        try:
            resolve_and_check_url(url, policy, tool="browser.engine")
        except SecurityViolationError as exc:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=str(exc),
                evidence={**self._base(receipt, attempt), "url": url},
            )

        timeout_ms = 30_000
        if raw_ctx.scope.resources.wall_time_ms is not None:
            timeout_ms = raw_ctx.scope.resources.wall_time_ms

        max_chars = 50_000
        if raw_ctx.scope.resources.output_bytes is not None:
            max_chars = min(max_chars, raw_ctx.scope.resources.output_bytes)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="playwright import failed",
                evidence=self._base(receipt, attempt),
            )

        title = ""
        content = ""
        final_url = url
        chosen_engine = ""

        try:
            with sync_playwright() as p:
                browser, chosen_engine = self._launch_browser(p)
                try:
                    context = browser.new_context(
                        java_script_enabled=True,
                        accept_downloads=False,
                        bypass_csp=False,
                        ignore_https_errors=False,
                        offline=False,
                    )
                    page = context.new_page()
                    
                    # Hardening: Intercept all requests to prevent SSRF from within the page
                    resolved_cache: dict[str, bool] = {}
                    
                    def handle_route(route: Any) -> None:
                        req_url = route.request.url
                        
                        # Data URIs and blob URIs are generally safe from network SSRF
                        if req_url.startswith("data:") or req_url.startswith("blob:"):
                            route.continue_()
                            return
                            
                        # Extract just the hostname to cache DNS lookups
                        try:
                            from urllib.parse import urlparse
                            host: str | None = urlparse(str(req_url)).hostname
                        except Exception:
                            host = None
                            
                        if host and host in resolved_cache:
                            if resolved_cache[host]:
                                route.continue_()
                            else:
                                route.abort("accessdenied")
                            return
                            
                        try:
                            resolve_and_check_url(req_url, policy, tool="browser.engine.intercept")
                            if host:
                                resolved_cache[host] = True
                            route.continue_()
                        except SecurityViolationError:
                            if host:
                                resolved_cache[host] = False
                            route.abort("accessdenied")
                            
                    page.route("**/*", handle_route)
                    
                    page.set_default_timeout(float(timeout_ms))
                    page.goto(url, wait_until="domcontentloaded")
                    final_url = page.url

                    # Re-check final URL after redirects
                    try:
                        resolve_and_check_url(
                            final_url, policy, tool="browser.engine"
                        )
                    except SecurityViolationError as exc:
                        return AdapterResult(
                            outcome=AppOutcome.FAILURE,
                            error=f"redirect target blocked: {exc}",
                            evidence={
                                **self._base(receipt, attempt),
                                "url": url,
                                "final_url": final_url,
                                "browser_mode": f"playwright_{chosen_engine}",
                            },
                        )

                    title = page.title() or ""
                    content = (
                        page.inner_text("body")
                        if contract.operation != "browser.navigate"
                        else ""
                    )
                    if not content and contract.operation in {
                        "browser.navigate",
                        "browser.read",
                        "browser.engine",
                    }:
                        content = page.inner_text("body")
                    content = content[:max_chars]
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001 — adapter boundary
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error=f"playwright error: {exc}",
                evidence={**self._base(receipt, attempt), "url": url},
            )

        evidence: dict[str, Any] = {
            **self._base(receipt, attempt),
            "url": url,
            "final_url": final_url,
            "title": title[:500],
            "text_preview": content[:2000],
            "browser_mode": f"playwright_{chosen_engine}",
            "postcondition": "page_fetched",
        }
        return AdapterResult(outcome=AppOutcome.SUCCESS, evidence=evidence)

    def _base(
        self, receipt: ExecutionReceipt, attempt: ExecutionAttempt
    ) -> dict[str, str]:
        return {"receipt_id": receipt.id, "attempt_id": attempt.id}