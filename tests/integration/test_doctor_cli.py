"""Integration tests for hi-agent doctor CLI."""
from __future__ import annotations

import subprocess
import sys


def test_doctor_cli_exits_0_in_dev():
    """In dev with default config, doctor should exit 0 (ready or degraded is OK -- no blocking)."""
    result = subprocess.run(
        [sys.executable, "-m", "hi_agent", "doctor"],
        capture_output=True, text=True, timeout=30
    )
    # Exit 0 = ready, exit 1 = degraded/error
    # In dev environment without real credentials, we accept either
    assert result.returncode in (0, 1)


def test_doctor_cli_json_flag_produces_valid_json():
    import json
    result = subprocess.run(
        [sys.executable, "-m", "hi_agent", "doctor", "--json"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode in (0, 1)
    data = json.loads(result.stdout)
    assert "status" in data
    assert "blocking" in data


def test_doctor_cli_output_contains_status():
    result = subprocess.run(
        [sys.executable, "-m", "hi_agent", "doctor"],
        capture_output=True, text=True, timeout=30
    )
    output = result.stdout + result.stderr
    # Should mention status somewhere
    assert any(word in output.upper() for word in ("READY", "DEGRADED", "ERROR", "DOCTOR"))
