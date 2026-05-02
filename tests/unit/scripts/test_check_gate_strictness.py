"""Stub unit tests: check_gate_strictness.py importability.

These tests verify that the check_gate_strictness script (when it exists)
can be imported without errors. If the script does not exist, tests skip.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_gate_strictness.py"


def _load_module() -> object:
    """Load check_gate_strictness if it exists, else skip."""
    if not _SCRIPT_PATH.exists():
        pytest.skip(reason="check_gate_strictness.py not yet created")
    spec = importlib.util.spec_from_file_location("check_gate_strictness", _SCRIPT_PATH)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # expiry_wave: Wave 29
    return mod


def test_script_is_importable() -> None:
    """check_gate_strictness.py must import without raising."""
    _load_module()


def test_script_exposes_main() -> None:
    """check_gate_strictness.py must expose a callable main()."""
    mod = _load_module()
    assert callable(getattr(mod, "main", None)), (
        "check_gate_strictness.py must define a main() function"
    )
