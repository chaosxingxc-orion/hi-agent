"""Smoke test for soak_24h.py driver loop (5-second run)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_soak_dry_run_emits_all_required_fields(tmp_path: Path) -> None:
    """5-second dry run must emit evidence JSON with all required fields."""
    import soak_24h

    exit_code = soak_24h.main([
        "--duration-seconds", "8",
        "--run-interval-seconds", "3",
        "--dry-run",
        "--out-dir", str(tmp_path),
    ])
    assert exit_code == 0

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1, f"Expected 1 evidence file, got: {files}"

    data = json.loads(files[0].read_text(encoding="utf-8"))

    required = [
        "release_head", "verified_head", "start_time", "end_time",
        "duration_seconds", "status", "runs_submitted", "runs_completed",
        "runs_failed", "duplicate_executions", "sigterm_injections",
        "health_samples", "results",
    ]
    for field in required:
        assert field in data, f"Missing required field: {field!r}"

    assert data["status"] == "dry_run"
    assert data["runs_submitted"] >= 1
    assert data["runs_completed"] == data["runs_submitted"]
    assert data["runs_failed"] == 0
    assert data["duplicate_executions"] == 0
    assert isinstance(data["results"], list)
    assert all(r["state"] == "dry_run" for r in data["results"])


def test_soak_dry_run_tracks_elapsed_time(tmp_path: Path) -> None:
    """dry-run results carry elapsed_wall_seconds field."""
    import soak_24h

    soak_24h.main([
        "--duration-seconds", "6",
        "--run-interval-seconds", "2",
        "--dry-run",
        "--out-dir", str(tmp_path),
    ])
    files = list(tmp_path.glob("*.json"))
    data = json.loads(files[0].read_text(encoding="utf-8"))

    assert all("elapsed_wall_seconds" in r for r in data["results"])


def test_soak_server_unreachable_exits_nonzero(tmp_path: Path) -> None:
    """When server is unreachable (and not dry-run), exit code must be non-zero."""
    import soak_24h

    exit_code = soak_24h.main([
        "--duration-seconds", "5",
        "--base-url", "http://127.0.0.1:19999",  # nothing listening here
        "--out-dir", str(tmp_path),
    ])
    assert exit_code != 0
