"""Tests for verify_clean_env wrapper truthfulness on failure/timeout."""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _import_vce():
    """Import verify_clean_env module, inserting scripts/ on sys.path if needed."""
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        return importlib.import_module("verify_clean_env")
    except ImportError as exc:
        pytest.skip(f"verify_clean_env not importable: {exc}")


def test_evidence_has_null_counts_on_timeout():
    """When timed_out=True, counts must be null not zero."""
    vce = _import_vce()

    builder = getattr(vce, "_build_evidence_json", None)
    if builder is None:
        pytest.skip("No _build_evidence_json function exposed")

    evidence = builder(
        profile="default-offline",
        cmd=["pytest", "tests/unit"],
        duration=600.0,
        timed_out=True,
        returncode=-1,
        stdout="",
        summary=None,
        release_head="abc12345",
    )
    assert evidence["summary_available"] is False
    assert evidence["collected"] is None, "collected must be None on timeout, not 0"
    assert evidence["failed"] is None, "failed must be None on timeout, not 0"
    assert evidence["passed"] is None, "passed must be None on timeout, not 0"
    assert evidence["errors"] is None, "errors must be None on timeout, not 0"
    assert evidence["timeout"] is True


def test_evidence_has_null_counts_on_no_summary():
    """When summary is None (crash/no report), counts must be null not zero."""
    vce = _import_vce()

    builder = getattr(vce, "_build_evidence_json", None)
    if builder is None:
        pytest.skip("No _build_evidence_json function exposed")

    evidence = builder(
        profile="default-offline",
        cmd=["pytest", "tests/unit"],
        duration=5.0,
        timed_out=False,
        returncode=-1,
        stdout="",
        summary=None,
        release_head="abc12345",
    )
    assert evidence["summary_available"] is False
    assert evidence["collected"] is None, "collected must be None on crash, not 0"
    assert evidence["failed"] is None, "failed must be None on crash, not 0"
    assert evidence["failure_reason"] == "no_summary"


def test_evidence_has_real_counts_on_success():
    """When summary is available, counts must be propagated from summary."""
    vce = _import_vce()

    builder = getattr(vce, "_build_evidence_json", None)
    if builder is None:
        pytest.skip("No _build_evidence_json function exposed")

    summary = {
        "summary_available": True,
        "status": "passed",
        "failure_reason": None,
        "collected": 42,
        "passed": 40,
        "failed": 0,
        "errors": 0,
        "skipped": 2,
    }
    evidence = builder(
        profile="default-offline",
        cmd=["pytest", "tests/unit"],
        duration=30.0,
        timed_out=False,
        returncode=0,
        stdout="",
        summary=summary,
        release_head="abc12345",
    )
    assert evidence["summary_available"] is True
    assert evidence["collected"] == 42
    assert evidence["passed"] == 40
    assert evidence["failed"] == 0
    assert evidence["skipped"] == 2
    assert evidence["status"] == "passed"
