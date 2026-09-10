from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from shea.security.exceptions import SecurityViolationError
from shea.security.filesystem_policy import FilesystemPolicy
from shea.security.network_policy import NetworkPolicy
from shea.security.runtime_checks import ResolvedUrl, realpath_under_roots, resolve_and_check_url


def test_realpath_under_root_allows_file(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("hi", encoding="utf-8")
    policy = FilesystemPolicy(allowed_roots=frozenset({str(root)}))

    real = realpath_under_roots(str(target), policy)
    assert real == target.resolve()


def test_realpath_blocks_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    policy = FilesystemPolicy(allowed_roots=frozenset({str(root)}))

    with pytest.raises(SecurityViolationError):
        realpath_under_roots(str(outside), policy)


def test_realpath_blocks_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "escape.txt"
    link.symlink_to(outside)
    policy = FilesystemPolicy(allowed_roots=frozenset({str(root)}))

    with pytest.raises(SecurityViolationError, match="escapes allowed roots"):
        realpath_under_roots(str(link), policy)


def test_resolve_and_check_url_blocks_private_after_dns() -> None:
    policy = NetworkPolicy(block_private_networks=True)
    # Force DNS to return loopback regardless of hostname
    fake_info = [(None, None, None, None, ("127.0.0.1", 80))]

    with (
        patch("shea.security.runtime_checks.socket.getaddrinfo", return_value=fake_info),
        pytest.raises(SecurityViolationError, match="not publicly routable"),
    ):
        resolve_and_check_url("http://example.com/", policy)


def test_resolve_and_check_url_returns_resolved_ip() -> None:
    policy = NetworkPolicy(block_private_networks=True)
    # Force DNS to return a public IP
    fake_info = [(None, None, None, None, ("93.184.216.34", 80))]

    with patch("shea.security.runtime_checks.socket.getaddrinfo", return_value=fake_info):
        result = resolve_and_check_url("http://example.com/", policy)
        assert isinstance(result, ResolvedUrl)
        assert result.url == "http://example.com/"
        assert result.host == "example.com"
        assert result.port == 80
        assert result.resolved_ip == "93.184.216.34"