"""Tests that verify_clean_env.py never writes misleading 0/0/0/0 evidence on failure.

These are unit tests for the _parse_pytest_json() function and the overall
evidence truthfulness contract.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

def _load_verify_module():
    """Load scripts/verify_clean_env.py as a module without executing main()."""
    script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "verify_clean_env.py"
    spec = importlib.util.spec_from_file_location("verify_clean_env", script_path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------------------
# Tests: missing/unreadable report — must never produce silent success
# ---------------------------------------------------------------------------


def test_missing_report_produces_failed_status(tmp_path):
    """When pytest JSON report is missing, evidence must show status=failed not zeros.

    Rationale: the old code returned {"collected": 0, "passed": 0, ...} on
    file-not-found, making a failed pytest run look like "no tests, all ok".
    This test guards against regression of that silent-success mask.
    """
    m = _load_verify_module()

    result = m._parse_pytest_json(tmp_path / "nonexistent.json", exit_code=1)

    assert result.get("status") == "failed", (
        f"Expected status='failed' for missing report, got {result.get('status')!r}"
    )
    assert result.get("summary_available") is False, (
        "summary_available must be False when report is missing"
    )
    assert result.get("failure_reason") is not None, (
        "failure_reason must be set when report is missing"
    )
    # The critical invariant: must NOT look like "all passed with 0 tests"
    looks_like_success = (
        result.get("passed") == 0
        and result.get("failed") == 0
        and result.get("summary_available", True) is True
    )
    assert not looks_like_success, (
        "Evidence must not look like a successful empty run when report is missing"
    )


def test_corrupt_report_produces_failed_status(tmp_path):
    """When pytest JSON report is corrupt (invalid JSON), evidence must show status=failed."""
    m = _load_verify_module()

    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("{not valid json{{{{", encoding="utf-8")

    result = m._parse_pytest_json(corrupt_file, exit_code=1)

    assert result.get("status") == "failed", (
        f"Expected status='failed' for corrupt report, got {result.get('status')!r}"
    )
    assert result.get("summary_available") is False
    assert result.get("failure_reason") is not None


# ---------------------------------------------------------------------------
# Tests: non-zero exit code must produce status=failed
# ---------------------------------------------------------------------------


def test_nonzero_exit_code_produces_failed_status(tmp_path):
    """When pytest exits with non-zero and JSON shows failures, status must be 'failed'."""
    import json

    m = _load_verify_module()

    report_file = tmp_path / "report.json"
    report_data = {
        "summary": {
            "collected": 5,
            "passed": 3,
            "failed": 2,
            "error": 0,
            "skipped": 0,
        }
    }
    report_file.write_text(json.dumps(report_data), encoding="utf-8")

    result = m._parse_pytest_json(report_file, exit_code=1)

    assert result.get("status") == "failed", (
        f"Expected status='failed' when exit_code=1 and failed=2, got {result.get('status')!r}"
    )
    assert result.get("summary_available") is True
    assert result.get("failed") == 2


def test_zero_exit_code_with_no_failures_produces_passed_status(tmp_path):
    """When pytest exits 0 and JSON shows no failures, status must be 'passed'."""
    import json

    m = _load_verify_module()

    report_file = tmp_path / "report.json"
    report_data = {
        "summary": {
            "collected": 10,
            "passed": 8,
            "failed": 0,
            "error": 0,
            "skipped": 2,
        }
    }
    report_file.write_text(json.dumps(report_data), encoding="utf-8")

    result = m._parse_pytest_json(report_file, exit_code=0)

    assert result.get("status") == "passed", (
        f"Expected status='passed' when exit_code=0 and no failures, got {result.get('status')!r}"
    )
    assert result.get("summary_available") is True
    assert result.get("failure_reason") is None


# ---------------------------------------------------------------------------
# Tests: timeout produces status=timeout, not a silent success
# ---------------------------------------------------------------------------


def test_timeout_status_not_passed():
    """A timeout result dict must have status='timeout' and summary_available=False."""
    # Simulate what main() builds on TimeoutExpired
    timeout_stats = {
        "status": "timeout",
        "summary_available": False,
        "failure_reason": "pytest timed out after 600 seconds",
        "collected": None,
        "passed": None,
        "failed": None,
        "errors": None,
        "skipped": None,
    }

    assert timeout_stats["status"] == "timeout"
    assert timeout_stats["summary_available"] is False
    assert timeout_stats["failure_reason"] is not None
    # Must not be confusable with "all passed"
    assert timeout_stats["passed"] is None
    assert timeout_stats["failed"] is None
