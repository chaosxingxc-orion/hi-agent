"""Unit tests for PathPolicy safe_resolve (P0-1c)."""

from __future__ import annotations

import sys

import pytest
from hi_agent.security.path_policy import PathPolicyViolation, safe_resolve


def test_traversal_blocked(tmp_path):
    """Path traversal via ../../ must be blocked."""
    with pytest.raises(PathPolicyViolation):
        safe_resolve(tmp_path, "../../../etc/passwd")


def test_absolute_path_blocked(tmp_path):
    """Absolute paths must be rejected by default."""
    with pytest.raises(PathPolicyViolation):
        safe_resolve(tmp_path, "/etc/passwd")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only: UNC paths", expiry_wave="Wave 16")
def test_windows_unc_blocked(tmp_path):
    """Windows UNC paths (\\\\server\\share) must be rejected."""
    with pytest.raises(PathPolicyViolation):
        safe_resolve(tmp_path, "\\\\server\\share\\file")


def test_windows_drive_blocked(tmp_path):
    """Windows drive-letter paths (C:\\...) must be rejected."""
    with pytest.raises(PathPolicyViolation):
        safe_resolve(tmp_path, "C:\\Windows\\System32\\cmd.exe")


def test_null_byte_blocked(tmp_path):
    """Null bytes in path must be rejected."""
    with pytest.raises(PathPolicyViolation):
        safe_resolve(tmp_path, "file\x00.txt")


def test_valid_relative_path_allowed(tmp_path):
    """A valid relative path within base_dir must be allowed."""
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "data.csv").write_text("x")
    result = safe_resolve(tmp_path, "subdir/data.csv")
    assert result == (tmp_path / "subdir" / "data.csv").resolve()


def test_allows_nested_relative(tmp_path):
    """Nested relative paths fully within base_dir must be allowed."""
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    (nested / "file.txt").write_text("hello")
    result = safe_resolve(tmp_path, "a/b/c/file.txt")
    assert result == (tmp_path / "a" / "b" / "c" / "file.txt").resolve()


def test_symlink_escape_blocked(tmp_path):
    """Symlink pointing outside base_dir must be blocked."""
    outside = tmp_path.parent / "outside_target.txt"
    outside.write_text("secret")
    link = tmp_path / "escape_link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform")
    with pytest.raises(PathPolicyViolation):
        safe_resolve(tmp_path, "escape_link.txt")
    outside.unlink(missing_ok=True)
