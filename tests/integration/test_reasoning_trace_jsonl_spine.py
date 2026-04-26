"""Integration test: ReasoningTrace JSONL spine round-trip (W2-C.1).

Verifies that ``RunManager._write_trace_stub`` populates the contract spine
(tenant_id, user_id, session_id, project_id) on the on-disk JSONL entry by
forwarding it from the originating ``ManagedRun``.

Strategy: rather than driving a full POST /runs lifecycle (heavy fixture),
we point ``HI_AGENT_DATA_DIR`` at a temp path, construct a ``ManagedRun``
with explicit spine, call ``_write_trace_stub`` directly, and read back the
JSONL line.  This pins the storage contract — callers populating the spine
on ``ManagedRun`` always materialize it on disk, so the audit trail remains
tenant-attributable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from hi_agent.server.run_manager import ManagedRun, RunManager


@pytest.mark.integration
def test_write_trace_stub_propagates_spine_to_jsonl(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A terminal run with a populated spine must write a JSONL entry that
    carries every spine field on disk."""
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))

    run = ManagedRun(
        run_id="run-spine-1",
        task_contract={"project_id": "proj-spine"},
        state="completed",
        created_at="2026-04-26T00:00:00+00:00",
        updated_at="2026-04-26T00:00:01+00:00",
        finished_at="2026-04-26T00:00:01+00:00",
        tenant_id="tenant-spine",
        user_id="user-spine",
        session_id="sess-spine",
        project_id="proj-spine",
        current_stage="finalize",
    )

    RunManager._write_trace_stub(run)

    trace_file = Path(tmp_path) / "traces" / f"{run.run_id}.jsonl"
    assert trace_file.exists(), (
        "Trace stub must write a .jsonl file when HI_AGENT_DATA_DIR is set."
    )

    lines = trace_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, f"Expected exactly one trace line, got {len(lines)}"

    entry = json.loads(lines[0])
    assert entry["run_id"] == "run-spine-1"
    assert entry["tenant_id"] == "tenant-spine"
    assert entry["user_id"] == "user-spine"
    assert entry["session_id"] == "sess-spine"
    assert entry["project_id"] == "proj-spine"


@pytest.mark.integration
def test_write_trace_stub_empty_spine_back_compat(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``ManagedRun`` constructed without spine fields (legacy callers)
    must still produce a valid JSONL entry with empty-string spine values."""
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))

    run = ManagedRun(
        run_id="run-spine-legacy",
        task_contract={},
        state="failed",
        created_at="t",
        updated_at="t",
    )

    RunManager._write_trace_stub(run)

    trace_file = Path(tmp_path) / "traces" / f"{run.run_id}.jsonl"
    assert trace_file.exists()
    entry = json.loads(trace_file.read_text(encoding="utf-8").splitlines()[0])

    # Spine fields are present but empty — the JSONL schema is stable even
    # when the run had no authenticated workspace.
    assert entry["tenant_id"] == ""
    assert entry["user_id"] == ""
    assert entry["session_id"] == ""
    assert entry["project_id"] == ""


@pytest.mark.integration
def test_write_trace_stub_no_data_dir_is_noop(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``HI_AGENT_DATA_DIR`` is unset, no file is written even if the
    run carries a populated spine."""
    monkeypatch.delenv("HI_AGENT_DATA_DIR", raising=False)

    run = ManagedRun(
        run_id="run-no-dir",
        task_contract={},
        state="completed",
        created_at="t",
        updated_at="t",
        tenant_id="tenant-x",
    )

    RunManager._write_trace_stub(run)

    # Nothing should appear under tmp_path.
    assert not (Path(tmp_path) / "traces").exists()
    # Also nothing in cwd "traces" that mentions our run_id.
    cwd_trace = Path(os.getcwd()) / "traces" / f"{run.run_id}.jsonl"
    assert not cwd_trace.exists()
