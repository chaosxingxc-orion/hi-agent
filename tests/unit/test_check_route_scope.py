"""Unit test for check_route_scope script."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "check_route_scope.py"


def test_script_exists():
    assert SCRIPT.exists(), f"check_route_scope.py not found at {SCRIPT}"


def test_check_route_scope_passes():
    """The script must exit 0 — all authenticated handlers have tenant scope."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"check_route_scope failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK check_route_scope" in result.stdout
