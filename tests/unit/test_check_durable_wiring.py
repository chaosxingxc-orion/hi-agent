"""Unit test for check_durable_wiring script."""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "check_durable_wiring.py"


def test_check_durable_wiring_passes():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"check_durable_wiring failed:\n{result.stdout}\n{result.stderr}"
