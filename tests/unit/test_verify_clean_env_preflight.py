"""Unit tests for verify_clean_env.py pre-flight permission check.

Layer 1 — Unit: tests _preflight_check() in isolation.
Mocks Path.mkdir or uses a writable tempdir to test pass/fail paths.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_clean_env import _preflight_check


class TestPreflightCheck:
    """Tests for the pre-flight directory permission check."""

    def test_writable_tempdir_passes(self, capsys: pytest.CaptureFixture) -> None:
        """Pre-flight check passes for a writable temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _preflight_check(tmpdir)

        assert result is True
        captured = capsys.readouterr()
        assert "ENV-CHECK-FAIL" not in captured.err

    def test_mkdir_failure_emits_env_check_fail(self, capsys: pytest.CaptureFixture) -> None:
        """When mkdir fails, ENV-CHECK-FAIL is emitted to stderr and False is returned."""
        bad_path = "/nonexistent/deep/path/that/cannot/be/created"

        # On Windows, this will simply fail because the root doesn't exist.
        # On Linux/Mac, same. We patch mkdir to raise OSError to be portable.
        with patch.object(Path, "mkdir", side_effect=OSError("permission denied")):
            result = _preflight_check(bad_path)

        assert result is False
        captured = capsys.readouterr()
        assert "ENV-CHECK-FAIL" in captured.err
        assert bad_path in captured.err
        assert "mkdir" in captured.err

    def test_write_failure_emits_env_check_fail(self, capsys: pytest.CaptureFixture) -> None:
        """When sentinel write fails, ENV-CHECK-FAIL is emitted to stderr."""
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            Path, "write_text", side_effect=OSError("read-only fs")
        ):
            result = _preflight_check(tmpdir)

        assert result is False
        captured = capsys.readouterr()
        assert "ENV-CHECK-FAIL" in captured.err
        assert "write" in captured.err

    def test_read_failure_emits_env_check_fail(self, capsys: pytest.CaptureFixture) -> None:
        """When sentinel read fails, ENV-CHECK-FAIL is emitted to stderr."""
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            Path, "read_text", side_effect=OSError("read error")
        ):
            result = _preflight_check(tmpdir)

        assert result is False
        captured = capsys.readouterr()
        assert "ENV-CHECK-FAIL" in captured.err

    def test_sentinel_cleaned_up_on_success(self) -> None:
        """Sentinel file is deleted after a successful pre-flight check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _preflight_check(tmpdir)
            sentinel = Path(tmpdir) / "_preflight_check_sentinel.txt"
            assert result is True
            assert not sentinel.exists(), "Sentinel file should be deleted after check"
