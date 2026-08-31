from __future__ import annotations

from shea.contracts.models import ToolRequest

from .exceptions import SecurityViolationError
from .filesystem_policy import FilesystemPolicy, is_path_allowed
from .network_policy import NetworkPolicy, is_url_allowed

_URL_SCHEMES = ("http://", "https://")


def _looks_like_url(value: str) -> bool:
    return value.startswith(_URL_SCHEMES)


def _looks_like_absolute_path(value: str) -> bool:
    return value.startswith("/")


class SecurityGate:
    """Pure pre-execution request scanner: walks a ToolRequest's
    arguments and checks any URL-shaped or absolute-path-shaped string
    value against the configured network/filesystem policies.

    This is a heuristic on argument *shape* (does it look like a URL or
    an absolute path?), not a schema-aware check — a tool with a known
    argument schema could do better, but this catches the common case
    (a 'url' or 'path'-style argument) without requiring every tool to
    declare its own argument schema up front.
    """

    def __init__(
        self,
        network_policy: NetworkPolicy | None = None,
        filesystem_policy: FilesystemPolicy | None = None,
    ) -> None:
        self._network_policy = network_policy or NetworkPolicy()
        self._filesystem_policy = filesystem_policy

    def check_request(self, request: ToolRequest) -> None:
        for key, value in request.arguments.items():
            if not isinstance(value, str):
                continue

            if _looks_like_url(value) and not is_url_allowed(value, self._network_policy):
                raise SecurityViolationError(
                    request.tool,
                    "ssrf",
                    f"argument {key!r} targets a disallowed host: {value!r}",
                )

            if (
                self._filesystem_policy is not None
                and _looks_like_absolute_path(value)
                and not is_path_allowed(value, self._filesystem_policy)
            ):
                raise SecurityViolationError(
                    request.tool,
                    "path_traversal",
                    f"argument {key!r} is outside the allowed filesystem scope: {value!r}",
                )