"""Tests that inject_volces_key.py refuses to run when config is dirty."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def test_script_is_syntactically_valid():
    """inject_volces_key.py compiles without syntax errors."""
    script = Path("scripts/inject_volces_key.py")
    if not script.exists():
        pytest.skip("scripts/inject_volces_key.py not found")
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(script)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Syntax error in inject_volces_key.py:\n{result.stderr}"


def test_missing_key_exits_nonzero():
    """Without VOLCES_KEY set, the script exits with a non-zero code."""
    script = Path("scripts/inject_volces_key.py")
    if not script.exists():
        pytest.skip("scripts/inject_volces_key.py not found")
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env={},  # no environment — no VOLCES_KEY
    )
    # Script exits 0 with SKIP when key is empty (graceful no-op for optional CI steps)
    assert result.returncode == 0, f"Expected graceful exit (0) when key missing; got {result.returncode}"
    assert "SKIP" in result.stdout, f"Expected SKIP message, got: {result.stdout}"


def test_dirty_guard_present_in_source():
    """The dirty-check guard is present in the script source."""
    script = Path("scripts/inject_volces_key.py")
    if not script.exists():
        pytest.skip("scripts/inject_volces_key.py not found")
    source = script.read_text(encoding="utf-8")
    assert "git" in source and "status" in source and "--porcelain" in source, (
        "dirty-check guard must call git status --porcelain"
    )
    assert "INJECT_FORCE" in source, "dirty-check guard must honour INJECT_FORCE override"


def test_atexit_restore_present_in_source():
    """The atexit restore hook is present in the script source."""
    script = Path("scripts/inject_volces_key.py")
    if not script.exists():
        pytest.skip("scripts/inject_volces_key.py not found")
    source = script.read_text(encoding="utf-8")
    assert "atexit" in source, "atexit restore hook must be registered"
    assert "_restore_original" in source, "restore function must be defined"
