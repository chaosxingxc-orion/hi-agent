"""Unit tests for atomic run-state persistence."""

from __future__ import annotations

import json
from pathlib import Path

import hi_agent.run_state_store.run_state as run_state_module
import pytest
from hi_agent.run_state_store import RunStateSnapshot, RunStateStore


def _make_snapshot(run_id: str) -> RunStateSnapshot:
    """Build a deterministic snapshot fixture.

    Args:
        run_id: Unique run identifier for the snapshot.

    Returns:
        RunStateSnapshot: Snapshot with stable test values.
    """
    return RunStateSnapshot(
        run_id=run_id,
        current_stage="S2_plan",
        stage_states={"S1_intake": "completed", "S2_plan": "running"},
        action_seq=2,
        task_views_count=1,
        result=None,
    )


def test_write_file_uses_temp_then_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Save should write to a temp file and atomically replace the target file."""
    state_path = tmp_path / "run_state.json"
    existing = {"run-old": _make_snapshot("run-old").to_dict()}
    state_path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

    captured: dict[str, object] = {}

    def _replace_and_fail(src: str | Path, dst: str | Path) -> None:
        src_path = Path(src)
        captured["src"] = src_path
        captured["dst"] = Path(dst)
        captured["temp_payload"] = json.loads(src_path.read_text(encoding="utf-8"))
        raise OSError("replace failed")

    monkeypatch.setattr(run_state_module.os, "replace", _replace_and_fail)

    store = RunStateStore(file_path=state_path)
    with pytest.raises(OSError, match="replace failed"):
        store.save(_make_snapshot("run-new"))

    assert captured["dst"] == state_path
    assert captured["src"] != state_path
    assert Path(captured["src"]).parent == state_path.parent
    assert "run-new" in captured["temp_payload"]

    # The existing state file must remain untouched when replace fails.
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert "run-old" in persisted
    assert "run-new" not in persisted


def test_read_file_returns_empty_dict_on_malformed_json(tmp_path: Path) -> None:
    """Store initialization should ignore malformed or truncated JSON safely."""
    state_path = tmp_path / "run_state.json"
    state_path.write_text('{"run-id": {"run_id": "run-id"', encoding="utf-8")

    store = RunStateStore(file_path=state_path)
    assert store.get("run-id") is None

    store.save(_make_snapshot("run-ok"))
    restored = RunStateStore(file_path=state_path).get("run-ok")
    assert restored is not None
    assert restored.run_id == "run-ok"
