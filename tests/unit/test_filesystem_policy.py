from __future__ import annotations

import pytest

from shea.security.filesystem_policy import FilesystemPolicy, is_path_allowed


@pytest.fixture
def policy() -> FilesystemPolicy:
    return FilesystemPolicy(allowed_roots=frozenset({"/home/shea/workspace"}))


def test_path_inside_allowed_root_is_allowed(policy: FilesystemPolicy) -> None:
    assert is_path_allowed("/home/shea/workspace/file.txt", policy) is True


def test_path_equal_to_allowed_root_is_allowed(policy: FilesystemPolicy) -> None:
    assert is_path_allowed("/home/shea/workspace", policy) is True


def test_path_outside_allowed_root_is_blocked(policy: FilesystemPolicy) -> None:
    assert is_path_allowed("/etc/passwd", policy) is False


def test_sibling_directory_with_shared_prefix_is_blocked(policy: FilesystemPolicy) -> None:
    """A naive string-prefix check would wrongly allow
    /home/shea/workspace-secrets because it starts with the allowed root
    string — this must not happen.
    """
    assert is_path_allowed("/home/shea/workspace-secrets/file.txt", policy) is False


def test_traversal_escaping_allowed_root_is_blocked(policy: FilesystemPolicy) -> None:
    assert is_path_allowed("/home/shea/workspace/../../../etc/passwd", policy) is False


def test_relative_path_is_blocked(policy: FilesystemPolicy) -> None:
    assert is_path_allowed("relative/path.txt", policy) is False


def test_multiple_allowed_roots() -> None:
    policy = FilesystemPolicy(allowed_roots=frozenset({"/data/a", "/data/b"}))
    assert is_path_allowed("/data/a/file.txt", policy) is True
    assert is_path_allowed("/data/b/file.txt", policy) is True
    assert is_path_allowed("/data/c/file.txt", policy) is False