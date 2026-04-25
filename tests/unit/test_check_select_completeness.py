"""Unit test for check_select_completeness script."""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "check_select_completeness.py"


def test_check_select_completeness_passes():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"check_select_completeness failed:\n{result.stdout}\n{result.stderr}"
    )
