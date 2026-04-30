"""Stub unit tests: check_score_artifact_consistency.py importability.

These tests verify that the check_score_artifact_consistency script (when it
exists) can be imported without errors. If the script does not exist, tests
skip and fall back to verifying check_score_cap.py (the existing related script).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_score_artifact_consistency.py"
_FALLBACK_PATH = REPO_ROOT / "scripts" / "check_score_cap.py"


def _load_module(path: Path) -> object:
    """Load module from path."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None, f"Cannot create spec for {path}"
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # expiry_wave: Wave 26
    return mod


def test_script_is_importable() -> None:
    """check_score_artifact_consistency.py (or check_score_cap.py) must import cleanly."""
    if _SCRIPT_PATH.exists():
        _load_module(_SCRIPT_PATH)
    elif _FALLBACK_PATH.exists():
        # Fallback: verify the related check_score_cap script is importable
        _load_module(_FALLBACK_PATH)
    else:
        pytest.skip(
            reason="neither check_score_artifact_consistency.py nor check_score_cap.py found"
        )


def test_fallback_score_cap_exposes_main() -> None:
    """check_score_cap.py must define a callable main()."""
    if not _FALLBACK_PATH.exists():
        pytest.skip(reason="check_score_cap.py not found")
    mod = _load_module(_FALLBACK_PATH)
    assert callable(getattr(mod, "main", None)), (
        "check_score_cap.py must define a main() function"
    )
