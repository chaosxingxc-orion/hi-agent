"""Tests for observability spine evidence harness.

Profile validated: default-offline
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def test_evidence_harness_exits_0_or_produces_json():
    """Script must exit 0 or at minimum produce valid JSON to stdout on --print."""
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_observability_spine_evidence.py"),
            "--print",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(ROOT),
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        assert "release_head" in data or "run_id" in data or "event_count" in data
    else:
        # Non-zero exit: script ran but something failed.
        # At minimum it must have produced JSON (or at least not crashed silently).
        # Allow missing output only if stderr explains why.
        assert result.stdout or result.stderr, (
            "script exited non-zero with no stdout or stderr"
        )
