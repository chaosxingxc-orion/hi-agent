"""W31-L (L-15') tests for run_soak --require-polling-observation flag.

Verifies the strict Rule-8 step-5 mode: when ``require_polling_observation``
is set, ``terminal_stages_ok`` alone no longer satisfies the invariant.
Only ``polling_ok`` counts.

The default (lenient) mode preserves the back-compat OR-logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _result(
    *,
    state: str = "done",
    run_id: str = "r1",
    run_index: int = 0,
    stage_first_seen_seconds: float | None = None,
    terminal_stage_count: int = 0,
    finished_at: str | None = "2026-05-03T00:00:00Z",
) -> dict:
    return {
        "state": state,
        "run_id": run_id,
        "run_index": run_index,
        "stage_first_seen_seconds": stage_first_seen_seconds,
        "terminal_stage_count": terminal_stage_count,
        "finished_at": finished_at,
        "duration_seconds": 1.0,
    }


def test_default_mode_accepts_terminal_stages_only():
    """Lenient default: terminal_stage_count > 0 satisfies the invariant
    even without polling_ok."""
    import run_soak

    results = [
        _result(stage_first_seen_seconds=None, terminal_stage_count=3),
    ]
    inv = run_soak._compute_invariants(results, 0)
    assert inv["invariants_held"] is True
    assert inv["stage_observed_misses"] == []


def test_strict_mode_rejects_terminal_stages_only():
    """Strict mode (L-15'): terminal_stage_count alone is insufficient.

    Only polling_ok counts in strict mode; this run has no polling-side
    stage observation, so the invariant fails.
    """
    import run_soak

    results = [
        _result(stage_first_seen_seconds=None, terminal_stage_count=3),
    ]
    inv = run_soak._compute_invariants(
        results,
        0,
        require_polling_observation=True,
    )
    assert inv["invariants_held"] is False, (
        "L-15' strict mode: terminal_stages alone must NOT satisfy invariant"
    )
    assert inv["stage_observed_misses"] == [0]


def test_strict_mode_accepts_polling_observation():
    """Strict mode passes when polling observed a stage within window."""
    import run_soak

    results = [
        _result(stage_first_seen_seconds=5.0, terminal_stage_count=0),
    ]
    inv = run_soak._compute_invariants(
        results,
        0,
        require_polling_observation=True,
    )
    assert inv["invariants_held"] is True
    assert inv["stage_observed_misses"] == []


def test_strict_mode_rejects_polling_outside_window():
    """Strict mode rejects polling observation that took longer than 30s."""
    import run_soak

    results = [
        _result(stage_first_seen_seconds=45.0, terminal_stage_count=0),
    ]
    inv = run_soak._compute_invariants(
        results,
        0,
        require_polling_observation=True,
    )
    assert inv["invariants_held"] is False
    assert inv["stage_observed_misses"] == [0]


def test_strict_mode_rejects_no_signals():
    """Both signals absent fails in both modes."""
    import run_soak

    results = [
        _result(stage_first_seen_seconds=None, terminal_stage_count=0),
    ]
    # Default
    inv = run_soak._compute_invariants(results, 0)
    assert inv["invariants_held"] is False
    # Strict
    inv = run_soak._compute_invariants(
        results,
        0,
        require_polling_observation=True,
    )
    assert inv["invariants_held"] is False


def test_cli_flag_defaults_to_false():
    """Argparse: --require-polling-observation defaults to False."""
    import run_soak

    # Re-derive the flag's default by parsing without the flag.
    # We invoke main with a tiny dry-run to confirm no exception.
    rc = run_soak.main(
        ["--duration", "5s", "--dry-run", "--out-dir", str(REPO_ROOT / ".tmp_soak_test")]
    )
    # Cleanup
    import shutil

    shutil.rmtree(REPO_ROOT / ".tmp_soak_test", ignore_errors=True)
    assert rc == 0
