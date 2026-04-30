"""W24-A: Integration tests for the observability spine evidence builder.

These tests exercise scripts/run_observability_spine.py and
scripts/check_observability_spine_completeness.py with the dev-mock LLM —
no real Volces/Anthropic/OpenAI calls.

The canonical evidence producer for `provenance: real` evidence is the
script invoked manually with --real-llm + VOLCES_API_KEY. These tests
verify the structural / fallback path and the gate's three-band exit.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_RUN = ROOT / "scripts" / "run_observability_spine.py"
SCRIPT_CHECK = ROOT / "scripts" / "check_observability_spine_completeness.py"


def _load_script_module():
    """Load run_observability_spine.py as a module, registering it in sys.modules.

    The module defines dataclasses with forward-reference annotations; if the
    module isn't registered in sys.modules before exec_module, dataclasses
    cannot resolve those annotations.
    """
    name = "run_observability_spine_under_test"
    if name in sys.modules:
        return sys.modules[name]
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, str(SCRIPT_RUN))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


def test_script_module_importable() -> None:
    """The script module must import cleanly without side effects."""
    mod = _load_script_module()
    # Sanity: 14 layers declared.
    assert len(mod._LAYER_TO_EVENT_TYPE) == 14
    assert "http_request" in mod._LAYER_TO_EVENT_TYPE
    assert "event_store" in mod._LAYER_TO_EVENT_TYPE
    # Counter-only layers and event-store layers must be disjoint.
    assert set(mod._COUNTER_LAYERS).isdisjoint(set(mod._EVENTSTORE_LAYERS))


def test_correlate_trace_id_returns_first_nonempty() -> None:
    """_correlate_trace_id picks the first non-empty trace_id."""
    mod = _load_script_module()
    events = [
        {"trace_id": "", "event_type": "x"},
        {"trace_id": "abc123", "event_type": "y"},
        {"trace_id": "abc123", "event_type": "z"},
    ]
    assert mod._correlate_trace_id(events) == "abc123"
    assert mod._correlate_trace_id([]) == ""
    assert mod._correlate_trace_id([{"trace_id": ""}]) == ""


def test_build_layer_events_with_high_coverage() -> None:
    """Build layer events with most layers covered (13/14 — fallback_recorder=0)."""
    mod = _load_script_module()

    run_id = "test-run-id"
    trace_id = "abc123def456"
    # Stored events covering 7 EventStore layers + tenant_context proxy.
    stored = [
        {"event_type": "run_queued", "tenant_id": "t1", "run_id": run_id,
         "trace_id": trace_id, "created_at": 1.0, "sequence": 0},
        {"event_type": "run_started", "tenant_id": "t1", "run_id": run_id,
         "trace_id": trace_id, "created_at": 2.0, "sequence": 1},
        {"event_type": "lease_acquired", "tenant_id": "t1", "run_id": run_id,
         "trace_id": trace_id, "created_at": 3.0, "sequence": 2},
        {"event_type": "heartbeat_renewed", "tenant_id": "t1", "run_id": run_id,
         "trace_id": trace_id, "created_at": 4.0, "sequence": 3},
        {"event_type": "llm_call", "tenant_id": "t1", "run_id": run_id,
         "trace_id": trace_id, "created_at": 5.0, "sequence": 4},
        {"event_type": "run_finalized", "tenant_id": "t1", "run_id": run_id,
         "trace_id": trace_id, "created_at": 6.0, "sequence": 5},
        {"event_type": "run_completed", "tenant_id": "t1", "run_id": run_id,
         "trace_id": trace_id, "created_at": 7.0, "sequence": 6},
    ]
    # Counter snapshot covering 5 of 6 counter layers (fallback_recorder=0).
    metrics = {
        "hi_agent_http_requests_total":             {"_total": 5.0},
        "hi_agent_spine_trace_id_propagated_total": {"_total": 5.0},
        "hi_agent_events_published_total":          {"_total": 7.0},
        "hi_agent_spine_llm_call_total":            {"_total": 1.0},
        "hi_agent_llm_fallback_total":              {"_total": 0.0},
        "hi_agent_events_stored_total":             {"_total": 7.0},
    }
    events, present, missing = mod._build_layer_events(
        run_id=run_id,
        trace_id=trace_id,
        stored_events=stored,
        metrics_snapshot=metrics,
        started_at="2026-04-30T00:00:00+00:00",
    )
    # Expected: 7 EventStore + 1 synthesized + 5 counter = 13
    assert len(events) == 13, f"got {len(events)} events: {present}"
    assert "fallback_recorder" in missing
    assert "tenant_context" in present
    # Every event must carry the same trace_id and run_id.
    for ev in events:
        assert ev.trace_id == trace_id, f"layer {ev.layer} trace_id mismatch: {ev.trace_id}"
        assert ev.run_id == run_id, f"layer {ev.layer} run_id mismatch: {ev.run_id}"


def test_build_layer_events_with_zero_counters() -> None:
    """When every counter is zero and no stored events, no layers are present."""
    mod = _load_script_module()
    events, present, missing = mod._build_layer_events(
        run_id="rid",
        trace_id="tid",
        stored_events=[],
        metrics_snapshot={},
        started_at="2026-04-30T00:00:00+00:00",
    )
    assert events == []
    assert present == []
    assert set(missing) == set(mod._LAYER_TO_EVENT_TYPE.keys())


def test_gate_returns_zero_for_existing_evidence() -> None:
    """The gate returns exit 0 (PASS or DEFER) — never FAIL — given any
    well-formed evidence. The repo carries spine evidence already, so this
    confirms the gate doesn't regress on a clean repo state."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_CHECK), "--json"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, (
        f"check_observability_spine_completeness exited {proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    out = json.loads(proc.stdout)
    assert out["check"] == "observability_spine_completeness"
    assert out["status"] in ("pass", "deferred")
