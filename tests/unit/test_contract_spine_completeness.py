"""Tests for the contract spine completeness gate (Rule 12, Wave 23 Track D).

Drives ``scripts/check_contract_spine_completeness.py`` against synthetic
fixture sources to verify both PASS and FAIL paths, plus exemption handling.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "check_contract_spine_completeness.py"


def _import_gate_module():
    """Import the gate script as a module so we can call its helpers directly."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_spine_gate_under_test", GATE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gate_runs_clean_on_repo() -> None:
    """The gate must exit 0 on the current repo (Track D acceptance)."""
    result = subprocess.run(
        [sys.executable, str(GATE)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"check_contract_spine_completeness.py failed unexpectedly:\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "PASS" in result.stdout


def test_gate_emits_json_when_requested() -> None:
    """--json flag must produce valid multistatus payload."""
    import json

    result = subprocess.run(
        [sys.executable, str(GATE), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["check"] == "contract_spine_completeness"
    assert payload["status"] == "pass"
    assert payload["missing"] == []
    assert payload["scanned_files"] > 0


def test_scan_detects_missing_field(tmp_path: Path) -> None:
    """A synthetic dataclass without tenant_id must produce a violation."""
    gate = _import_gate_module()
    sample = tmp_path / "missing.py"
    sample.write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass

            @dataclass
            class NoTenant:
                run_id: str = ""
            """
        ).strip(),
        encoding="utf-8",
    )
    classes_with_tenant: set[str] = set()
    # Patch REPO_ROOT for this call
    gate.REPO_ROOT = tmp_path
    violations = gate._scan_file("missing.py", classes_with_tenant)
    assert len(violations) == 1
    assert violations[0]["class"] == "NoTenant"
    assert "tenant_id" in violations[0]["reason"]


def test_scan_respects_process_internal_marker(tmp_path: Path) -> None:
    """A class marked '# scope: process-internal' must be exempt."""
    gate = _import_gate_module()
    sample = tmp_path / "exempt.py"
    sample.write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass

            # scope: process-internal — pure value object
            @dataclass
            class ValueObj:
                amount: int = 0
            """
        ).strip(),
        encoding="utf-8",
    )
    gate.REPO_ROOT = tmp_path
    violations = gate._scan_file("exempt.py", set())
    assert violations == []


def test_scan_passes_when_field_present(tmp_path: Path) -> None:
    """A class with tenant_id must not produce a violation."""
    gate = _import_gate_module()
    sample = tmp_path / "ok.py"
    sample.write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass

            @dataclass
            class WithTenant:
                tenant_id: str
            """
        ).strip(),
        encoding="utf-8",
    )
    gate.REPO_ROOT = tmp_path
    violations = gate._scan_file("ok.py", set())
    assert violations == []


def test_inheritance_from_spine_base_is_exempt(tmp_path: Path) -> None:
    """A subclass of a base that has tenant_id is implicitly covered."""
    gate = _import_gate_module()
    sample = tmp_path / "inherit.py"
    sample.write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass

            @dataclass
            class Base:
                tenant_id: str = ""

            @dataclass
            class Sub(Base):
                extra: str = ""
            """
        ).strip(),
        encoding="utf-8",
    )
    gate.REPO_ROOT = tmp_path
    classes_with_tenant = gate._collect_classes_with_tenant(["inherit.py"])
    assert "Base" in classes_with_tenant
    violations = gate._scan_file("inherit.py", classes_with_tenant)
    # Sub omits tenant_id but inherits Base — must not be flagged.
    sub_violations = [v for v in violations if v["class"] == "Sub"]
    assert sub_violations == []


def test_synthetic_fail_run_returns_nonzero(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: a fixture tree with a missing field must drive exit 1."""
    gate = _import_gate_module()
    fake = tmp_path / "fakecontracts.py"
    fake.write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass

            @dataclass
            class MissingTenant:
                value: int = 0
            """
        ).strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gate, "SCAN_DIRS", [])
    monkeypatch.setattr(gate, "SCAN_FILES", ["fakecontracts.py"])
    rc = gate.main([])
    assert rc == 1


@pytest.mark.parametrize(
    "target",
    [
        "StartRunRequest",
        "SignalRunRequest",
        "OpenBranchRequest",
        "BranchStateUpdateRequest",
        "ApprovalRequest",
        "KernelManifest",
        "StartRunResponse",
        "QueryRunResponse",
        "TraceRuntimeView",
    ],
)
def test_all_nine_track_d_targets_have_tenant_id(target: str) -> None:
    """Each of the nine Track D dataclasses must declare tenant_id."""
    from hi_agent.contracts import requests as mod

    cls = getattr(mod, target)
    fields = cls.__dataclass_fields__
    assert "tenant_id" in fields, f"{target} missing required tenant_id field"
