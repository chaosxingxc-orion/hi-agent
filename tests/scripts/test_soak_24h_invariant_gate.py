"""W32-C.5 tests for soak_24h.py invariant-gated provenance.

Verifies that ``provenance="real"`` requires ALL of:
  - duration >= 86400s
  - runs_failed == 0
  - duplicate_executions == 0
  - llm_fallback_count == 0

Any deviation downgrades to ``provenance="structural"``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _import_soak_24h():
    import importlib
    return importlib.import_module("soak_24h")


soak_24h = _import_soak_24h()


def _read_evidence(out_dir: Path) -> dict:
    """Read the single evidence JSON written into out_dir."""
    files = list(out_dir.glob("*.json"))
    assert len(files) == 1, f"expected 1 evidence file, got {len(files)}: {files}"
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_24h_clean_run_yields_real_provenance(tmp_path):
    """24h+ duration + zero failures + zero dups + zero fallback => real."""
    results = [
        {"run_index": i, "run_id": f"r-{i}", "state": "completed",
         "duration_seconds": 1.0, "error": None}
        for i in range(10)
    ]
    soak_24h._write_evidence(
        sha="abc1234",
        full_sha="abc1234" + "0" * 33,
        start_time="2026-05-03T00:00:00Z",
        end_time="2026-05-04T00:00:01Z",
        duration_seconds=86400.0,
        results=results,
        samples=[],
        dry_run=False,
        sigterm_injections=0,
        out_dir=tmp_path,
        llm_fallback_count=0,
    )
    ev = _read_evidence(tmp_path)
    assert ev["provenance"] == "real", ev
    assert ev["llm_fallback_count"] == 0


def test_24h_with_duplicate_yields_structural_provenance(tmp_path):
    """24h+ duration but one duplicate run_id => structural, not real."""
    results = [
        {"run_index": 0, "run_id": "r-1", "state": "completed",
         "duration_seconds": 1.0, "error": None},
        # Duplicate run_id under a fresh run_index — exercises the
        # ``len(all_ids) - len(set(all_ids))`` duplicate detection.
        {"run_index": 1, "run_id": "r-1", "state": "completed",
         "duration_seconds": 1.0, "error": None},
    ]
    soak_24h._write_evidence(
        sha="abc1234",
        full_sha="abc1234" + "0" * 33,
        start_time="2026-05-03T00:00:00Z",
        end_time="2026-05-04T00:00:01Z",
        duration_seconds=86400.5,
        results=results,
        samples=[],
        dry_run=False,
        sigterm_injections=0,
        out_dir=tmp_path,
        llm_fallback_count=0,
    )
    ev = _read_evidence(tmp_path)
    assert ev["duplicate_executions"] == 1
    assert ev["provenance"] == "structural", (
        "duplicate_executions>0 must downgrade real -> structural"
    )


def test_24h_with_failure_yields_structural_provenance(tmp_path):
    """24h+ duration but one failure => structural, not real."""
    results = [
        {"run_index": 0, "run_id": "r-1", "state": "completed",
         "duration_seconds": 1.0, "error": None},
        {"run_index": 1, "run_id": "r-2", "state": "failed",
         "duration_seconds": 1.0, "error": "boom"},
    ]
    soak_24h._write_evidence(
        sha="abc1234",
        full_sha="abc1234" + "0" * 33,
        start_time="2026-05-03T00:00:00Z",
        end_time="2026-05-04T00:00:01Z",
        duration_seconds=90000.0,
        results=results,
        samples=[],
        dry_run=False,
        sigterm_injections=0,
        out_dir=tmp_path,
        llm_fallback_count=0,
    )
    ev = _read_evidence(tmp_path)
    assert ev["runs_failed"] >= 1
    assert ev["provenance"] == "structural"


def test_24h_with_fallback_yields_structural_provenance(tmp_path):
    """24h+ duration but llm_fallback_count > 0 => structural, not real."""
    results = [
        {"run_index": 0, "run_id": "r-1", "state": "completed",
         "duration_seconds": 1.0, "error": None},
    ]
    soak_24h._write_evidence(
        sha="abc1234",
        full_sha="abc1234" + "0" * 33,
        start_time="2026-05-03T00:00:00Z",
        end_time="2026-05-04T00:00:01Z",
        duration_seconds=86400.0,
        results=results,
        samples=[],
        dry_run=False,
        sigterm_injections=0,
        out_dir=tmp_path,
        llm_fallback_count=2,
    )
    ev = _read_evidence(tmp_path)
    assert ev["llm_fallback_count"] == 2
    assert ev["provenance"] == "structural"


def test_short_duration_yields_shape_verified(tmp_path):
    """Sub-24h duration => shape_verified regardless of cleanliness."""
    results = [
        {"run_index": 0, "run_id": "r-1", "state": "completed",
         "duration_seconds": 1.0, "error": None},
    ]
    soak_24h._write_evidence(
        sha="abc1234",
        full_sha="abc1234" + "0" * 33,
        start_time="2026-05-03T00:00:00Z",
        end_time="2026-05-03T01:00:00Z",
        duration_seconds=3600.0,
        results=results,
        samples=[],
        dry_run=False,
        sigterm_injections=0,
        out_dir=tmp_path,
        llm_fallback_count=0,
    )
    ev = _read_evidence(tmp_path)
    assert ev["provenance"] == "shape_verified"
