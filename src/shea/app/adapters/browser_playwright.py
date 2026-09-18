from __future__ import annotations

import importlib.util
import platform
from pathlib import Path
from typing import Any

from shea.app.adapters.browser_profiles import (
    assert_profile_dir_allowed,
    plan_browser_launch,
)
from shea.app.contracts import (
    AdapterResult,
    ExecutionAttempt,
    ExecutionContract,
    ExecutionReceipt,
)
from shea.app.enums import AppOutcome
from shea.app.ports.process import AdapterContext
from shea.security.content_trust import UntrustedExternalData
from shea.security.exceptions import SecurityViolationError
from shea.security.network_policy import NetworkPolicy
from shea.security.runtime_checks import resolve_and_check_url


def playwright_available() -> bool:
    """True only if the package imports *and* this OS is a known-supported host.

    Shea must run on older macOS/Linux without modern browser binaries.
    Unsupported hosts fall through to browser.local (stdlib HTTP document mode).
    """
    if importlib.util.find_spec("playwright") is None:
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

    def _launch_persistent_context(
        self, p: Any, profile_dir: str, browser_scope: Any
    ) -> tuple[Any, str]:
        errors: list[str] = []
        for name, engine in (
            ("chromium", p.chromium),
            ("firefox", p.firefox),
            ("webkit", p.webkit),
        ):
            try:
                context = engine.launch_persistent_context(
                    profile_dir,
                    headless=True,
                    accept_downloads=browser_scope.allow_downloads,
                )
                return context, name
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")
        raise RuntimeError(
            "no supported browser binary found for persistent context. "
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

        browser_scope = raw_ctx.scope.browser
        plan = plan_browser_launch(browser_scope)
        operation = contract.operation

        if operation.endswith(".download") and not browser_scope.allow_downloads:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="downloads disabled by BrowserScope",
                evidence=self._base(receipt, attempt),
            )
        if operation.endswith(".upload") and not browser_scope.allow_uploads:
            return AdapterResult(
                outcome=AppOutcome.FAILURE,
                error="uploads disabled by BrowserScope",
                evidence=self._base(receipt, attempt),
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
        identities: list[str] = [url]

        try:
            with sync_playwright() as p:
                browser: Any = None
                if plan.ephemeral:
                    browser, chosen_engine = self._launch_browser(p)
                    context = browser.new_context(
                        java_script_enabled=True,
                        accept_downloads=browser_scope.allow_downloads,
                        bypass_csp=False,
                        ignore_https_errors=False,
                        offline=False,
                    )
                else:
                    raw_dir = contract.arguments.get("profile_dir")
                    if not isinstance(raw_dir, str):
                        return AdapterResult(
                            outcome=AppOutcome.FAILURE,
                            error="profile_dir required",
                            evidence=self._base(receipt, attempt),
                        )
                    profile_path = assert_profile_dir_allowed(raw_dir, browser_scope)
                    context, chosen_engine = self._launch_persistent_context(
                        p, str(profile_path), browser_scope
                    )
                try:
                    page = context.new_page()
                    
                    # Hardening: Intercept every request to prevent SSRF from within the page.
                    def handle_route(route: Any) -> None:
                        req_url = route.request.url
                        
                        # Data URIs and blob URIs are generally safe from network SSRF
                        if req_url.startswith("data:") or req_url.startswith("blob:"):
                            route.continue_()
                            return
                            
                        try:
                            resolve_and_check_url(req_url, policy, tool="browser.engine.intercept")
                            route.continue_()
                        except SecurityViolationError:
                            route.abort("accessdenied")
                            
                    page.route("**/*", handle_route)
                    
                    page.set_default_timeout(float(timeout_ms))

                    download_path: str | None = None
                    download_name: str | None = None
                    if operation.endswith(".download"):
                        selector = contract.arguments.get("selector")
                        with page.expect_download() as download_info:
                            if isinstance(selector, str) and selector:
                                page.goto(url, wait_until="domcontentloaded")
                                page.locator(selector).click()
                            else:
                                page.goto(url, wait_until="domcontentloaded")
                        download = download_info.value
                        failure = download.failure()
                        if failure is not None:
                            return AdapterResult(
                                outcome=AppOutcome.FAILURE,
                                error=f"download failed: {failure}",
                                evidence=self._base(receipt, attempt),
                            )
                        download_name = download.suggested_filename
                        raw_download_path = contract.arguments.get("download_path")
                        if isinstance(raw_download_path, str) and raw_download_path:
                            destination = self._assert_filesystem_path_allowed(
                                raw_download_path, raw_ctx.scope.filesystem.allowed_roots
                            )
                            download.save_as(str(destination))
                            download_path = str(destination)
                        else:
                            temporary_path = download.path()
                            download_path = str(temporary_path) if temporary_path else None
                    else:
                        page.goto(url, wait_until="domcontentloaded")
                        if operation.endswith(".upload"):
                            selector = contract.arguments.get("selector")
                            raw_upload_path = contract.arguments.get("file_path")
                            if not isinstance(selector, str) or not selector:
                                return AdapterResult(
                                    outcome=AppOutcome.FAILURE,
                                    error="upload selector required",
                                    evidence=self._base(receipt, attempt),
                                )
                            if not isinstance(raw_upload_path, str) or not raw_upload_path:
                                return AdapterResult(
                                    outcome=AppOutcome.FAILURE,
                                    error="upload file_path required",
                                    evidence=self._base(receipt, attempt),
                                )
                            upload_path = self._assert_filesystem_path_allowed(
                                raw_upload_path, raw_ctx.scope.filesystem.allowed_roots
                            )
                            page.locator(selector).set_input_files(str(upload_path))
                    final_url = page.url
                    if final_url != url:
                        identities.append(final_url)

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
                    context.close()
                    if browser is not None:
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
            "untrusted_content_block": UntrustedExternalData(
                source_url=final_url,
                content_type="text/html",
                payload=content[:2000]
            ).to_safe_prompt_block(),
            "browser_mode": f"playwright_{chosen_engine}",
            "postcondition": "page_fetched",
            "destination_identity_chain": identities,
            "content_trust": browser_scope.content_trust,
            "business_success": None,
            "profile_mode": plan.mode.value,
            "ephemeral": plan.ephemeral,
            "download_path": download_path,
            "download_filename": download_name,
            "upload_completed": operation.endswith(".upload"),
        }
        return AdapterResult(outcome=AppOutcome.SUCCESS, evidence=evidence)

    @staticmethod
    def _assert_filesystem_path_allowed(
        path: str, allowed_roots: frozenset[str]
    ) -> Path:
        resolved = Path(path).resolve()
        for root_value in allowed_roots:
            root = Path(root_value).resolve()
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue
        raise SecurityViolationError(
            "browser",
            "filesystem",
            f"path {str(resolved)!r} is outside the allowed filesystem roots",
        )

    def _base(
        self, receipt: ExecutionReceipt, attempt: ExecutionAttempt
    ) -> dict[str, str]:
        return {"receipt_id": receipt.id, "attempt_id": attempt.id}