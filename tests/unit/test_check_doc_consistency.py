"""Unit tests for check_doc_consistency script."""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "check_doc_consistency.py"


def test_check_doc_consistency_passes():
    """After Track E fixes, consistency check must pass."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"check_doc_consistency failed:\n{result.stdout}\n{result.stderr}"
    )
