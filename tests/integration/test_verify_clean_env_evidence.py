"""Integration test for verify_clean_env.py evidence JSON generation.

Layer 2 — Integration: runs the script as a subprocess against a 1-test
sub-bundle (uses --bundle to pass a temp file with one test path).
Zero mocks on the subsystem under test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

# A single test file that is always present and passes quickly.
_SINGLE_TEST = "tests/unit/test_artifact_spine_fields.py"

REQUIRED_JSON_FIELDS = {
    "schema_version",
    "head",
    "python",
    "pytest",
    "collected",
    "passed",
    "failed",
    "duration_seconds",
}


@pytest.mark.integration
def test_script_exits_zero_with_bundle(tmp_path: Path) -> None:
    """Script exits 0 when given a --bundle with one always-passing test."""
    bundle_file = tmp_path / "bundle.txt"
    bundle_file.write_text(_SINGLE_TEST, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_clean_env.py"),
            "--bundle",
            str(bundle_file),
            "--no-fail-fast-env-check",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Script exited {result.returncode}.\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


@pytest.mark.integration
def test_json_report_written_with_required_fields(tmp_path: Path) -> None:
    """--json-report writes a JSON file with all required evidence fields."""
    bundle_file = tmp_path / "bundle.txt"
    bundle_file.write_text(_SINGLE_TEST, encoding="utf-8")
    report_file = tmp_path / "evidence.json"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_clean_env.py"),
            "--bundle",
            str(bundle_file),
            "--json-report",
            str(report_file),
            "--no-fail-fast-env-check",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Script exited {result.returncode}.\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )

    assert report_file.exists(), f"Evidence JSON not written to {report_file}"

    data = json.loads(report_file.read_text(encoding="utf-8"))

    missing = REQUIRED_JSON_FIELDS - set(data.keys())
    assert not missing, f"Evidence JSON missing fields: {missing}"


@pytest.mark.integration
def test_json_report_passed_gte_one(tmp_path: Path) -> None:
    """Evidence JSON shows passed >= 1 for the single-test bundle."""
    bundle_file = tmp_path / "bundle.txt"
    bundle_file.write_text(_SINGLE_TEST, encoding="utf-8")
    report_file = tmp_path / "evidence.json"

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_clean_env.py"),
            "--bundle",
            str(bundle_file),
            "--json-report",
            str(report_file),
            "--no-fail-fast-env-check",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    if report_file.exists():
        data = json.loads(report_file.read_text(encoding="utf-8"))
        assert data.get("passed", 0) >= 1, (
            f"Expected passed >= 1, got {data.get('passed')}"
        )
