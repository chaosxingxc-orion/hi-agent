"""Tests for check_metric_producers.py.

Profile validated: default-offline
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def test_metric_producers_exits_0_or_1():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_metric_producers.py"), "--json"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(ROOT),
    )
    assert result.returncode in (0, 1)
    data = json.loads(result.stdout)
    assert "check" in data
    assert "status" in data
    assert "orphan_count" in data


def test_no_orphan_metrics():
    """All metrics in _METRIC_DEFS must have at least one producer callsite."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_metric_producers.py"), "--json"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(ROOT),
    )
    data = json.loads(result.stdout)
    orphans = data.get("orphans", [])
    assert data["status"] == "pass", f"Orphan metrics found: {orphans}"
