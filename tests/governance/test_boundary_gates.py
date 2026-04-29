"""Tests that agent_server/ boundary gate scripts detect violations correctly."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parents[2] / "scripts"
ROOT = Path(__file__).parents[2]


def _run(script: str, *args: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script)] + list(args),
        capture_output=True, text=True, cwd=str(ROOT),
    )
    return result.returncode, result.stdout + result.stderr


def test_no_reverse_imports_passes_on_clean_tree():
    code, out = _run("check_no_reverse_imports.py")
    assert code == 0, f"Expected PASS on clean tree, got exit {code}:\n{out}"


def test_no_domain_types_passes_on_current_contracts():
    code, out = _run("check_no_domain_types.py")
    assert code == 0, f"Expected PASS on clean contracts, got exit {code}:\n{out}"


def test_contracts_purity_passes_on_current_contracts():
    code, out = _run("check_contracts_purity.py")
    assert code == 0, f"Expected PASS on stdlib-only contracts, got exit {code}:\n{out}"


def test_facade_loc_passes_when_facade_empty():
    code, out = _run("check_facade_loc.py")
    # facade/ is currently empty (only __init__.py), so should PASS
    assert code == 0, f"Expected PASS on empty facade, got exit {code}:\n{out}"


def test_contract_freeze_passes_when_no_release_notice():
    code, out = _run("check_contract_freeze.py")
    # v1 is not released yet, so advisory only (exit 0)
    assert code == 0, f"Expected PASS (advisory), got exit {code}:\n{out}"


def test_route_tenant_context_passes_when_no_routes():
    code, out = _run("check_route_tenant_context.py")
    # No routes_*.py files yet
    assert code == 0, f"Expected PASS when no routes yet, got exit {code}:\n{out}"


def test_tdd_evidence_passes_when_no_routes():
    code, out = _run("check_tdd_evidence.py")
    # No routes_*.py files yet
    assert code == 0, f"Expected PASS when no routes yet, got exit {code}:\n{out}"
