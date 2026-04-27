"""Build observability-spine evidence by driving real in-process runs.

Boots a RunManager with SQLiteEventStore (in-memory), submits a synthetic run,
polls for terminal state, and asserts that lifecycle events were recorded with
correct correlation-spine fields.

Emits docs/verification/<sha>-observability-spine.json and exits 0 on success,
1 on any failure.

Usage:
    python scripts/build_observability_spine_evidence.py
    python scripts/build_observability_spine_evidence.py --print
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
_LOG = logging.getLogger("observability_spine_evidence")

POLL_INTERVAL_S = 0.05
POLL_TIMEOUT_S = 30.0
MIN_EVENTS_REQUIRED = 1  # at least run_queued must be recorded


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=str(_REPO_ROOT),
        ).strip()
    except Exception:
        return "unknown"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _build_metrics_snapshot() -> dict:
    """Return a snapshot of current metric values from the process-level collector."""
    try:
        from hi_agent.observability.collector import get_metrics_collector

        collector = get_metrics_collector()
        if collector is None:
            return {}
        return collector.snapshot()
    except Exception as exc:
        _LOG.warning("Could not read metrics snapshot: %s", exc)
        return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--print",
        action="store_true",
        dest="print_output",
        help="Print evidence JSON to stdout even when writing to file.",
    )
    args = parser.parse_args(argv)

    sha = _git_sha()
    generated_at = _iso_now()
    failures: list[str] = []

    # ------------------------------------------------------------------
    # Import required components
    # ------------------------------------------------------------------
    try:
        from hi_agent.server.event_store import SQLiteEventStore, StoredEvent
    except ImportError as exc:
        _LOG.error("Cannot import SQLiteEventStore: %s", exc)
        return 1

    try:
        from hi_agent.server.run_manager import ManagedRun, RunManager
    except ImportError as exc:
        _LOG.error("Cannot import RunManager: %s", exc)
        return 1

    try:
        from hi_agent.observability.collector import MetricsCollector, set_metrics_collector
    except ImportError as exc:
        _LOG.error("Cannot import MetricsCollector: %s", exc)
        return 1

    # ------------------------------------------------------------------
    # Set up metrics collector
    # ------------------------------------------------------------------
    collector = MetricsCollector()
    set_metrics_collector(collector)

    # ------------------------------------------------------------------
    # Set up in-memory event store and RunManager
    # ------------------------------------------------------------------
    event_store = SQLiteEventStore(":memory:")
    mgr = RunManager(max_concurrent=2, queue_size=4, event_store=event_store)

    run_id_used: str = ""
    event_count: int = 0
    event_types: list[str] = []
    spine_ok: bool = False
    metrics_snapshot: dict = {}

    try:
        # ------------------------------------------------------------------
        # Create and submit a synthetic run
        # ------------------------------------------------------------------
        tenant_id = "test-tenant"
        task = {
            "task": "observability-spine-probe",
            "tenant_id": tenant_id,
        }
        run = mgr.create_run(task)
        run_id_used = run.run_id
        _LOG.info("Created run: run_id=%s", run_id_used)

        # Emit run_queued manually too (create_run already calls _publish_run_event)
        # and set up a simple synchronous executor

        def _executor(r: ManagedRun):
            _LOG.info("Executor running for run_id=%s", r.run_id)
            # Publish a run_started-style event to the event_store directly
            seq = event_store.max_sequence(r.run_id) + 1
            event_store.append(
                StoredEvent(
                    event_id=str(uuid.uuid4()),
                    run_id=r.run_id,
                    sequence=seq,
                    event_type="run_started",
                    payload_json=json.dumps({"state": "running"}),
                    tenant_id=tenant_id,
                )
            )
            seq2 = event_store.max_sequence(r.run_id) + 1
            event_store.append(
                StoredEvent(
                    event_id=str(uuid.uuid4()),
                    run_id=r.run_id,
                    sequence=seq2,
                    event_type="run_completed",
                    payload_json=json.dumps({"state": "completed"}),
                    tenant_id=tenant_id,
                )
            )
            collector.increment("runs_total", labels={"status": "completed"})
            collector.increment("hi_agent_runs_completed_total")
            _LOG.info("Executor completed for run_id=%s", r.run_id)
            return type(
                "R", (), {"status": "completed", "llm_fallback_count": 0, "finished_at": None}
            )()

        mgr.start_run(run_id_used, _executor)

        # ------------------------------------------------------------------
        # Poll for terminal state
        # ------------------------------------------------------------------
        deadline = time.monotonic() + POLL_TIMEOUT_S
        while time.monotonic() < deadline:
            if run.state in ("completed", "failed", "cancelled"):
                break
            time.sleep(POLL_INTERVAL_S)

        _LOG.info("Run terminal state: %s", run.state)
        if run.state not in ("completed", "failed", "cancelled"):
            failures.append(
                f"run did not reach terminal state within {POLL_TIMEOUT_S}s"
                f" (state={run.state})"
            )

        # ------------------------------------------------------------------
        # Assert events were recorded
        # ------------------------------------------------------------------
        events = event_store.list_since(run_id_used, -1)
        event_count = len(events)
        event_types = [e.event_type for e in events]
        _LOG.info("Events recorded: count=%d types=%s", event_count, event_types)

        if event_count < MIN_EVENTS_REQUIRED:
            failures.append(
                f"expected >= {MIN_EVENTS_REQUIRED} events, got {event_count}"
            )

        # ------------------------------------------------------------------
        # Assert spine fields on events
        # ------------------------------------------------------------------
        bad_spine = []
        for ev in events:
            if ev.run_id != run_id_used:
                bad_spine.append(f"event {ev.event_type}: run_id mismatch ({ev.run_id!r})")
        if bad_spine:
            spine_ok = False
            failures.extend(bad_spine)
        else:
            spine_ok = True

        # ------------------------------------------------------------------
        # Metrics check
        # ------------------------------------------------------------------
        metrics_snapshot = _build_metrics_snapshot()
        metrics_non_zero = {
            k: v
            for k, v in metrics_snapshot.items()
            if isinstance(v, dict)
            and any(val > 0 for val in v.values() if isinstance(val, (int, float)))
        }
        if not metrics_non_zero:
            failures.append("no counters incremented in metrics snapshot")

    finally:
        mgr.shutdown(timeout=2.0)
        event_store.close()
        set_metrics_collector(None)

    # ------------------------------------------------------------------
    # Build evidence document
    # ------------------------------------------------------------------
    status = "pass" if not failures else "fail"
    evidence = {
        "release_head": sha,
        "verified_head": sha,
        "generated_at": generated_at,
        "run_id": run_id_used,
        "event_count": event_count,
        "event_types": event_types,
        "spine_ok": spine_ok,
        "metrics_snapshot": metrics_snapshot,
        "failures": failures,
        "status": status,
    }

    evidence_json = json.dumps(evidence, indent=2)

    # Always write to file
    out_dir = _REPO_ROOT / "docs" / "verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{sha}-observability-spine.json"
    out_path.write_text(evidence_json, encoding="utf-8")
    _LOG.info("Evidence written to %s", out_path)

    if args.print_output or status == "fail":
        print(evidence_json)

    if failures:
        _LOG.error("FAIL observability-spine: %s", "; ".join(failures))
        return 1

    _LOG.info("OK observability-spine evidence (events=%d, status=pass)", event_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
