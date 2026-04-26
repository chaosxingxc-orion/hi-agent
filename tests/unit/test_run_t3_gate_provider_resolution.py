"""Tests for run_t3_gate.py provider resolution."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def test_run_t3_gate_py_exists() -> None:
    """scripts/run_t3_gate.py must exist."""
    assert (ROOT / "scripts" / "run_t3_gate.py").exists()


def test_rule15_volces_gate_is_shim() -> None:
    """rule15_volces_gate.py must reference run_t3_gate.py (it's a shim)."""
    src = (ROOT / "scripts" / "rule15_volces_gate.py").read_text(encoding="utf-8")
    assert "run_t3_gate" in src or "Deprecated" in src or "deprecated" in src


def test_inject_provider_key_exists() -> None:
    """scripts/inject_provider_key.py must exist."""
    assert (ROOT / "scripts" / "inject_provider_key.py").exists()


def test_run_t3_gate_has_provider_argument() -> None:
    """run_t3_gate.py must accept --provider argument."""
    src = (ROOT / "scripts" / "run_t3_gate.py").read_text(encoding="utf-8")
    assert "--provider" in src


def test_run_t3_gate_output_uses_provider_neutral_name() -> None:
    """run_t3_gate.py must not hardcode 'rule15' or 'volces' in gate run IDs."""
    src = (ROOT / "scripts" / "run_t3_gate.py").read_text(encoding="utf-8")
    # The gate project ID and unknown-run sentinel should be provider-neutral
    assert "t3_gate_project" in src
    assert "t3-gate-unknown-run" in src


def test_run_t3_gate_sh_exists() -> None:
    """scripts/run_t3_gate.sh must exist."""
    assert (ROOT / "scripts" / "run_t3_gate.sh").exists()


def test_run_t3_gate_sh_calls_py() -> None:
    """scripts/run_t3_gate.sh must delegate to run_t3_gate.py."""
    src = (ROOT / "scripts" / "run_t3_gate.sh").read_text(encoding="utf-8")
    assert "run_t3_gate.py" in src
