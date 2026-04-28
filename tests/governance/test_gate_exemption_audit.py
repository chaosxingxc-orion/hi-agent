"""W18-C1: Gate exemption audit -- verifies no unaccounted gate weakenings exist."""
from __future__ import annotations

import json
import subprocess
import sys


def test_check_gate_strictness_passes():
    """check_gate_strictness.py must exit 0 with status:pass after C1 fixes."""
    result = subprocess.run(
        [sys.executable, "scripts/check_gate_strictness.py", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"check_gate_strictness.py failed:\n{result.stdout}\n{result.stderr}"
    )
    data = json.loads(result.stdout)
    assert data["status"] == "pass", (
        f"Expected status:pass, got {data['status']}. Violations:\n"
        + json.dumps(data.get("violations", []), indent=2)
    )
    assert data["violations_found"] == 0, (
        f"Expected 0 violations, got {data['violations_found']}"
    )
