"""Unit tests: release_gate.py emits record_fallback on silent-skip paths.

Layer 1 — Unit: the function under test is check_prod_e2e_recent() in
release_gate.py.  The lazy ``from hi_agent.observability.fallback import
record_fallback`` inside each except block is patched at its source module so
all call sites pick up the same mock.
"""

from __future__ import annotations

import json
import unittest.mock as mock
from pathlib import Path

_RF_PATH = "hi_agent.observability.fallback.record_fallback"


def test_record_fallback_called_on_corrupt_json(tmp_path: Path) -> None:
    """A corrupt episode JSON file triggers record_fallback with reason='episode_json_corrupt'."""
    ep_dir = tmp_path / "episodes"
    ep_dir.mkdir()
    corrupt_file = ep_dir / "bad-episode.json"
    corrupt_file.write_text("NOT VALID JSON {{{", encoding="utf-8")

    from hi_agent.operator_tools.release_gate import check_prod_e2e_recent

    with mock.patch(_RF_PATH) as mock_rf:
        check_prod_e2e_recent(max_age_hours=48, episodic_dir=str(ep_dir))

    calls = [
        c for c in mock_rf.call_args_list
        if c.kwargs.get("reason") == "episode_json_corrupt"
    ]
    assert len(calls) >= 1, (
        f"Expected record_fallback(reason='episode_json_corrupt'), "
        f"got: {mock_rf.call_args_list}"
    )
    assert calls[0].args[0] == "heuristic"


def test_record_fallback_called_on_invalid_timestamp(tmp_path: Path) -> None:
    """An episode with an unparseable timestamp triggers record_fallback.

    Reason: 'episode_timestamp_invalid'.
    """
    ep_dir = tmp_path / "episodes"
    ep_dir.mkdir()
    episode = {
        "runtime_mode": "prod-real",
        "completed_at": "NOT-A-TIMESTAMP",
    }
    (ep_dir / "ts-bad.json").write_text(json.dumps(episode), encoding="utf-8")

    from hi_agent.operator_tools.release_gate import check_prod_e2e_recent

    with mock.patch(_RF_PATH) as mock_rf:
        check_prod_e2e_recent(max_age_hours=48, episodic_dir=str(ep_dir))

    calls = [
        c for c in mock_rf.call_args_list
        if c.kwargs.get("reason") == "episode_timestamp_invalid"
    ]
    assert len(calls) >= 1, (
        f"Expected record_fallback(reason='episode_timestamp_invalid'), "
        f"got: {mock_rf.call_args_list}"
    )
    assert calls[0].args[0] == "heuristic"


def test_no_record_fallback_on_valid_episode(tmp_path: Path) -> None:
    """A valid prod-real episode does NOT trigger any record_fallback call."""
    import datetime

    ep_dir = tmp_path / "episodes"
    ep_dir.mkdir()
    recent_ts = datetime.datetime.now(datetime.UTC).isoformat()
    episode = {
        "runtime_mode": "prod-real",
        "completed_at": recent_ts,
    }
    (ep_dir / "good.json").write_text(json.dumps(episode), encoding="utf-8")

    from hi_agent.operator_tools.release_gate import check_prod_e2e_recent

    with mock.patch(_RF_PATH) as mock_rf:
        check_prod_e2e_recent(max_age_hours=48, episodic_dir=str(ep_dir))

    assert mock_rf.call_count == 0, (
        f"Unexpected record_fallback calls: {mock_rf.call_args_list}"
    )
