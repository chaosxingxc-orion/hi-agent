"""Unit test for check_validate_before_mutate script."""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "check_validate_before_mutate.py"


def test_check_validate_before_mutate_passes():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"check_validate_before_mutate failed:\n{result.stdout}\n{result.stderr}"
    )
