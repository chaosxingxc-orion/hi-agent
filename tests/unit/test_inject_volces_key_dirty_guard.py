"""Tests that inject_provider_key.py (and its volces shim) behave correctly."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def test_volces_shim_is_syntactically_valid():
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


def test_provider_key_script_is_syntactically_valid():
    """inject_provider_key.py compiles without syntax errors."""
    script = Path("scripts/inject_provider_key.py")
    if not script.exists():
        pytest.skip("scripts/inject_provider_key.py not found")
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(script)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Syntax error in inject_provider_key.py:\n{result.stderr}"


def test_missing_key_exits_nonzero():
    """Without any provider key set, inject_provider_key.py exits nonzero."""
    script = Path("scripts/inject_provider_key.py")
    if not script.exists():
        pytest.skip("scripts/inject_provider_key.py not found")
    result = subprocess.run(
        [sys.executable, str(script), "--provider", "volces"],
        capture_output=True,
        text=True,
        env={},  # no environment — no API keys
    )
    assert result.returncode != 0, f"Expected nonzero exit when key missing; got {result.returncode}"
    assert "ERROR" in result.stderr or "no key" in result.stderr.lower(), (
        f"Expected error message about missing key, got: {result.stderr}"
    )


def test_restore_function_present_in_source():
    """The restore function is present in inject_provider_key.py."""
    script = Path("scripts/inject_provider_key.py")
    if not script.exists():
        pytest.skip("scripts/inject_provider_key.py not found")
    source = script.read_text(encoding="utf-8")
    assert "_restore" in source, "restore function must be defined"
    assert "--restore" in source, "--restore flag must be documented"


def test_provider_key_script_supports_multiple_providers():
    """inject_provider_key.py accepts --provider argument with known providers."""
    script = Path("scripts/inject_provider_key.py")
    if not script.exists():
        pytest.skip("scripts/inject_provider_key.py not found")
    source = script.read_text(encoding="utf-8")
    for provider in ("volces", "anthropic", "openai", "auto"):
        assert provider in source, f"Provider '{provider}' must be supported"
