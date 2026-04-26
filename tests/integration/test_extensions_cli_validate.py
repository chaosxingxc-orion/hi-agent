"""Integration tests — hi-agent extensions validate CLI subcommand.

Wave 10.5 W5-F: tests that the validate subcommand accepts a manifest JSON
file and prints PASS/FAIL with the correct exit code.

Layer 2 (Integration): real CLI entry point; no mocks on the subsystem under test.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _run_cli(*args: str) -> tuple[int, str, str]:
    """Run the hi-agent CLI with the given arguments.

    Returns:
        (exit_code, stdout, stderr)
    """
    result = subprocess.run(
        [sys.executable, "-m", "hi_agent", *args],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Valid manifest
# ---------------------------------------------------------------------------


def test_validate_valid_manifest_exits_zero_and_prints_pass():
    """A valid manifest JSON should exit 0 and print PASS."""
    manifest = {
        "name": "test-extension",
        "version": "1.0.0",
        "manifest_kind": "plugin",
        "schema_version": 1,
        "posture_support": {"dev": True, "research": True, "prod": True},
        "required_posture": "any",
        "tenant_scope": "tenant",
        "dangerous_capabilities": [],
        "config_schema": None,
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(manifest, f)
        path = f.name

    try:
        rc, stdout, stderr = _run_cli("extensions", "validate", path)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr={stderr!r}"
        assert "PASS" in stdout, f"Expected PASS in stdout, got {stdout!r}"
    finally:
        Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Invalid manifests
# ---------------------------------------------------------------------------


def test_validate_invalid_manifest_kind_exits_nonzero():
    """A manifest with an unsupported manifest_kind should exit non-zero and print FAIL."""
    manifest = {
        "name": "bad-extension",
        "version": "1.0.0",
        "manifest_kind": "unsupported_type",
        "schema_version": 1,
        "posture_support": {"dev": True},
        "required_posture": "any",
        "tenant_scope": "tenant",
        "dangerous_capabilities": [],
        "config_schema": None,
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(manifest, f)
        path = f.name

    try:
        rc, stdout, stderr = _run_cli("extensions", "validate", path)
        assert rc != 0, f"Expected non-zero exit, got {rc}"
        combined = stdout + stderr
        assert "FAIL" in combined, f"Expected FAIL in output, got combined={combined!r}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_validate_empty_name_exits_nonzero():
    """A manifest with empty name should exit non-zero."""
    manifest = {
        "name": "",
        "version": "1.0.0",
        "manifest_kind": "plugin",
        "schema_version": 1,
        "posture_support": {"dev": True},
        "required_posture": "any",
        "tenant_scope": "tenant",
        "dangerous_capabilities": [],
        "config_schema": None,
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(manifest, f)
        path = f.name

    try:
        rc, _stdout, _stderr = _run_cli("extensions", "validate", path)
        assert rc != 0, f"Expected non-zero exit, got {rc}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_validate_nonexistent_file_exits_nonzero():
    """Non-existent manifest file should exit non-zero with FAIL."""
    rc, stdout, stderr = _run_cli("extensions", "validate", "/nonexistent/path/manifest.json")
    assert rc != 0
    combined = stdout + stderr
    assert "FAIL" in combined


def test_validate_empty_posture_support_exits_nonzero():
    """A manifest with empty posture_support should exit non-zero."""
    manifest = {
        "name": "ok-name",
        "version": "1.0.0",
        "manifest_kind": "plugin",
        "schema_version": 1,
        "posture_support": {},
        "required_posture": "any",
        "tenant_scope": "tenant",
        "dangerous_capabilities": [],
        "config_schema": None,
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(manifest, f)
        path = f.name

    try:
        rc, _stdout, _stderr = _run_cli("extensions", "validate", path)
        assert rc != 0
    finally:
        Path(path).unlink(missing_ok=True)
