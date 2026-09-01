from __future__ import annotations

import pytest

from shea.contracts.models import ToolRequest
from shea.security.exceptions import SecurityViolationError
from shea.security.filesystem_policy import FilesystemPolicy
from shea.security.gate import SecurityGate
from shea.security.network_policy import NetworkPolicy


def test_allows_ordinary_request() -> None:
    gate = SecurityGate()
    request = ToolRequest(
        request_id="req-1", tool="weather", action="lookup", arguments={"city": "Nairobi"}
    )
    gate.check_request(request)  # must not raise


def test_blocks_ssrf_target_in_url_shaped_argument() -> None:
    gate = SecurityGate()
    request = ToolRequest(
        request_id="req-1",
        tool="fetch",
        action="get",
        arguments={"url": "http://169.254.169.254/latest/meta-data/"},
    )
    with pytest.raises(SecurityViolationError) as exc_info:
        gate.check_request(request)
    assert exc_info.value.category == "ssrf"


def test_argument_key_name_does_not_matter_for_url_detection() -> None:
    """Unlike a narrower "only checks arguments named 'url'" approach,
    the gate scans every string-valued argument by shape.
    """
    gate = SecurityGate()
    request = ToolRequest(
        request_id="req-1",
        tool="fetch",
        action="get",
        arguments={"target": "http://127.0.0.1/admin"},
    )
    with pytest.raises(SecurityViolationError):
        gate.check_request(request)


def test_blocks_path_outside_allowed_root() -> None:
    gate = SecurityGate(
        filesystem_policy=FilesystemPolicy(allowed_roots=frozenset({"/workspace"}))
    )
    request = ToolRequest(
        request_id="req-1", tool="read_file", action="read", arguments={"path": "/etc/passwd"}
    )
    with pytest.raises(SecurityViolationError) as exc_info:
        gate.check_request(request)
    assert exc_info.value.category == "path_traversal"


def test_allows_path_inside_allowed_root() -> None:
    gate = SecurityGate(
        filesystem_policy=FilesystemPolicy(allowed_roots=frozenset({"/workspace"}))
    )
    request = ToolRequest(
        request_id="req-1",
        tool="read_file",
        action="read",
        arguments={"path": "/workspace/notes.txt"},
    )
    gate.check_request(request)  # must not raise


def test_no_filesystem_policy_skips_path_checks() -> None:
    gate = SecurityGate(filesystem_policy=None)
    request = ToolRequest(
        request_id="req-1", tool="read_file", action="read", arguments={"path": "/etc/passwd"}
    )
    gate.check_request(request)  # must not raise; no policy configured


def test_non_string_arguments_are_ignored() -> None:
    gate = SecurityGate()
    request = ToolRequest(
        request_id="req-1", tool="tool", action="do", arguments={"count": 5, "flag": True}
    )
    gate.check_request(request)  # must not raise


def test_custom_network_policy_is_used() -> None:
    gate = SecurityGate(network_policy=NetworkPolicy(allowed_hosts=frozenset({"api.example.com"})))
    request = ToolRequest(
        request_id="req-1", tool="fetch", action="get", arguments={"url": "https://other.com/x"}
    )
    with pytest.raises(SecurityViolationError):
        gate.check_request(request)