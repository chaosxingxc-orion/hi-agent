"""Anchor 11 regression: L0 JSONL must be flushed before L0Summarizer reads it.

Playbook Anchor 11 requires that ``_finalize_run`` close/flush the
``RawMemoryStore`` JSONL file before ``L0Summarizer.summarize_run`` reads it from
disk. If the tail events remain buffered in Python's IO layer, the summarizer
sees fewer lines than the in-memory record list, and the last-written events
are silently lost.

Incident guarded: R6 H-4 — the final few raw events of a run were dropped from
the L2 DailySummary because the JSONL writer was not flushed/closed before the
summarizer opened the file.

No internal components are mocked. Only the summarizer's ``summarize_run`` is
wrapped to intercept the arguments it was called with, so the test can read the
disk file at the exact moment the summarizer sees it. (CLAUDE.md: documented
observation-only interception, not a replacement.)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.l0_raw import RawEventRecord, RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor
from hi_agent.trajectory.stage_graph import StageGraph

from tests.helpers.kernel_adapter_fixture import MockKernel


def _two_stage_graph() -> StageGraph:
    g = StageGraph()
    g.add_edge("stage_a", "stage_b")
    return g


@pytest.mark.integration
def test_l0_file_is_flushed_before_summarizer_reads_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L0 JSONL on disk must contain every appended event when L0Summarizer runs.

    Guards R6 H-4: the unflushed-tail bug. We append N>=5 raw events through a
    real RawMemoryStore pointed at tmp_path, call _finalize_run('completed'),
    and verify that at the exact moment L0Summarizer.summarize_run() is invoked
    the JSONL file on disk contains all N records — including the very last one.
    """
    run_id = "anchor-11-flush-run"
    base_dir = tmp_path  # {base_dir}/logs/memory/L0/{run_id}.jsonl

    # Real RawMemoryStore with file persistence enabled.
    raw_memory = RawMemoryStore(run_id=run_id, base_dir=base_dir)

    # Build a minimal executor wired to this raw_memory.
    contract = TaskContract(task_id="anchor-11-flush", goal="L0 flush order guard")
    kernel = MockKernel(strict_mode=False)
    executor = RunExecutor(
        contract,
        kernel,
        stage_graph=_two_stage_graph(),
        raw_memory=raw_memory,
        event_emitter=EventEmitter(),
        compressor=MemoryCompressor(),
        acceptance_policy=AcceptancePolicy(),
        cts_budget=CTSExplorationBudget(),
        policy_versions=PolicyVersionSet(),
    )
    executor._run_id = run_id

    # Append N>=5 raw events directly (bypassing stage execution) so the test
    # fully controls which records must end up on disk before summarization.
    written_events: list[RawEventRecord] = []
    for i in range(6):
        record = RawEventRecord(
            event_type="stage_complete" if i % 2 == 0 else "result",
            payload={"stage_id": "stage_a", "seq": i, "note": f"raw-event-{i}"},
        )
        raw_memory.append(record)
        written_events.append(record)
    expected_count = len(written_events)

    # Intercept L0Summarizer.summarize_run to record what the disk looked like
    # at the exact moment it was called. We delegate to the real implementation.
    from hi_agent.memory import l0_summarizer as _l0_mod

    observed: dict[str, object] = {}
    real_summarize = _l0_mod.L0Summarizer.summarize_run

    def _observing_summarize(self, run_id_arg: str, base_dir_arg: Path):
        log_path = Path(base_dir_arg) / "logs" / "memory" / "L0" / f"{run_id_arg}.jsonl"
        # Capture disk state at the summarizer's view of the world.
        if log_path.exists():
            with log_path.open(encoding="utf-8") as fh:
                lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        else:
            lines = []
        observed["log_path"] = log_path
        observed["lines_at_summarize"] = lines
        return real_summarize(self, run_id_arg, base_dir_arg)

    monkeypatch.setattr(_l0_mod.L0Summarizer, "summarize_run", _observing_summarize)  # B1: SUT-internal mock — schedule replacement with boundary mock  # noqa: E501  # expiry_wave: Wave 30

    # Point the finalizer at our tmp_path via raw_memory._base_dir (already set).
    assert raw_memory._base_dir == base_dir

    # Run finalization — this is the code path under test.
    executor._finalize_run("completed")

    # --- Assertions ---
    assert "lines_at_summarize" in observed, (
        "L0Summarizer.summarize_run was never invoked; finalize chain is broken."
    )
    lines = observed["lines_at_summarize"]
    log_path = observed["log_path"]
    assert isinstance(lines, list)

    # R6 H-4 core assertion: every appended record is on disk at summarize time.
    assert len(lines) == expected_count, (
        f"L0 JSONL had {len(lines)} lines at summarize time; expected {expected_count}. "
        "Unflushed tail — R6 H-4 regression."
    )

    # Explicit guard for the *last* written record — the one most likely to be
    # lost to an unflushed buffer.
    last_note = f"raw-event-{expected_count - 1}"
    assert any(last_note in ln for ln in lines), (
        f"Last appended event {last_note!r} missing from JSONL at summarize time; "
        "this is the exact R6 H-4 symptom."
    )

    # Bonus: after finalize, the file on disk should still have exactly N lines.
    assert isinstance(log_path, Path)
    with log_path.open(encoding="utf-8") as fh:
        final_lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    assert len(final_lines) == expected_count
