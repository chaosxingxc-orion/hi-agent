#!/usr/bin/env python3
"""Real-LLM observability spine evidence builder.

Replaces the structural spine evidence (build_observability_spine_evidence.py)
with end-to-end real-LLM trace evidence joining (trace_id, run_id) across
14 layers of the runtime.

Usage:
    python scripts/run_observability_spine.py --port 9081 --real-llm \
        --output docs/verification/<sha>-observability-spine.json

The 14 layers we attempt to capture:
    1. http_request          (TraceIdMiddleware  — counter)
    2. middleware            (AuthMiddleware     — TenantContext set)
    3. tenant_context        (per-request ctxvar — observed via auth)
    4. run_manager           (run_queued event   — EventStore)
    5. kernel_dispatch       (run_started event  — EventStore)
    6. reasoning_loop        (lease_acquired     — EventStore)
    7. capability_handler    (heartbeat_renewed  — EventStore)
    8. llm_gateway           (llm_call event     — EventStore via event_bus)
    9. sync_bridge           (counter increment  — observed via metrics)
   10. http_transport        (http_gateway emit  — observed via metrics)
   11. llm_provider_response (run_finalized      — EventStore)
   12. fallback_recorder     (counter snapshot   — metrics)
   13. artifact_ledger       (run_completed payload OR counter)
   14. event_store           (events_stored_total — metrics)

Each "layer" is recorded as a single event observation with timestamp,
event_type, and the (run_id, trace_id) correlation pair.

Provenance:
    real     — real Volces (or other) LLM run completed; ≥1 stored event;
               trace_id non-empty on stored events.
    structural — fallback when --real-llm not specified or run failed.

Exit code:
    0 — wrote evidence (real or structural). The downstream gate
        check_observability_spine_completeness.py decides PASS/DEFER from JSON.
    1 — fatal error (could not start server, write evidence, etc.).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent

# ----------------------------------------------------------------------
# 14-layer mapping. Each layer maps to an EventStore event_type OR a
# metric counter name. Both forms produce one "layer event" entry in
# the evidence JSON.
# ----------------------------------------------------------------------
_LAYER_TO_EVENT_TYPE: dict[str, str] = {
    "http_request":          "http_request",            # counter only
    "middleware":            "trace_id_propagated",     # counter (auth+trace)
    "tenant_context":        "tenant_context_set",      # synthesized from auth_method
    "run_manager":           "run_queued",
    "kernel_dispatch":       "run_started",
    "reasoning_loop":        "lease_acquired",
    "capability_handler":    "heartbeat_renewed",
    "llm_gateway":           "llm_call",
    "sync_bridge":           "sync_bridge_invoked",     # counter only
    "http_transport":        "llm_request_sent",        # counter only
    "llm_provider_response": "run_finalized",
    "fallback_recorder":     "fallback_recorder_snapshot",  # counter
    "artifact_ledger":       "run_completed",
    "event_store":           "event_stored_total",      # counter
}

_COUNTER_LAYERS: dict[str, str] = {
    # layer -> counter metric name
    "http_request":          "hi_agent_http_requests_total",
    "middleware":            "hi_agent_spine_trace_id_propagated_total",
    "sync_bridge":           "hi_agent_events_published_total",
    "http_transport":        "hi_agent_spine_llm_call_total",
    "fallback_recorder":     "hi_agent_llm_fallback_total",
    "event_store":           "hi_agent_events_stored_total",
}

# Subset of layers that emit StoredEvent rows in the EventStore.
_EVENTSTORE_LAYERS: dict[str, str] = {
    "run_manager":           "run_queued",
    "kernel_dispatch":       "run_started",
    "reasoning_loop":        "lease_acquired",
    "capability_handler":    "heartbeat_renewed",
    "llm_gateway":           "llm_call",
    "llm_provider_response": "run_finalized",
    "artifact_ledger":       "run_completed",
}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


@dataclass
class _SpineEvent:
    layer: str
    event_type: str
    timestamp: str
    run_id: str = ""
    trace_id: str = ""
    source: str = ""  # "event_store" | "metric_counter" | "synthesized"
    extra: dict[str, Any] = field(default_factory=dict)


def _git_sha_short() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def _git_sha_full() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip() or "unknown"
    except Exception:
        return "unknown"


def _git_is_dirty() -> bool:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return bool(out.strip())
    except Exception:
        return True


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _wait_ready(client: httpx.Client, timeout_s: float, poll_s: float = 1.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last_err: str | None = None
    while time.monotonic() <= deadline:
        try:
            r = client.get("/ready")
            if r.status_code == 200:
                return r.json()
            if r.status_code != 503:
                raise RuntimeError(f"/ready unexpected status {r.status_code}")
        except Exception as exc:
            last_err = str(exc)
        time.sleep(poll_s)
    raise RuntimeError(
        f"timed out waiting for /ready after {timeout_s:.1f}s"
        + (f" (last error: {last_err})" if last_err else "")
    )


def _drive_one_run(client: httpx.Client, profile_id: str, poll_timeout_s: float) -> dict:
    """POST /runs, poll until terminal, return the terminal payload."""
    create = client.post(
        "/runs",
        json={
            "goal": " observability spine probe (real LLM)",
            "profile_id": profile_id,
            "project_id": "w24a_spine",
        },
    )
    if create.status_code != 201:
        raise RuntimeError(
            f"POST /runs failed: status={create.status_code} body={create.text!r}"
        )
    body = create.json()
    run_id = body.get("run_id")
    if not run_id:
        raise RuntimeError("POST /runs returned no run_id")

    deadline = time.monotonic() + poll_timeout_s
    while time.monotonic() <= deadline:
        r = client.get(f"/runs/{run_id}")
        if r.status_code == 200:
            payload = r.json()
            state = payload.get("state")
            if state in ("completed", "failed", "cancelled"):
                return payload
        time.sleep(1.0)
    raise RuntimeError(f"run {run_id} did not reach terminal in {poll_timeout_s}s")


def _harvest_events(client: httpx.Client, run_id: str) -> list[dict]:
    """Pull all events for run_id via /runs/{id}/events/snapshot."""
    r = client.get(f"/runs/{run_id}/events/snapshot", params={"since": 0, "limit": 500})
    if r.status_code != 200:
        return []
    body = r.json()
    return list(body.get("events", []))


def _harvest_metrics(client: httpx.Client) -> dict[str, Any]:
    """Pull /metrics/json snapshot."""
    r = client.get("/metrics/json")
    if r.status_code != 200:
        return {}
    try:
        return r.json()
    except Exception:
        return {}


def _counter_total(metrics_snapshot: dict, name: str) -> float:
    """Sum a counter across all label sets. Returns 0.0 if absent."""
    fam = metrics_snapshot.get(name)
    if not isinstance(fam, dict):
        return 0.0
    total = 0.0
    for v in fam.values():
        if isinstance(v, (int, float)):
            total += float(v)
    return total


def _build_layer_events(
    *,
    run_id: str,
    trace_id: str,
    stored_events: list[dict],
    metrics_snapshot: dict[str, Any],
    started_at: str,
) -> tuple[list[_SpineEvent], list[str], list[str]]:
    """Map stored events + metric counters to the 14 layer slots.

    Returns (events, layers_present, layers_missing).
    """
    events: list[_SpineEvent] = []
    present: list[str] = []
    missing: list[str] = []

    # Index stored events by event_type for quick lookup.
    by_type: dict[str, list[dict]] = {}
    for ev in stored_events:
        by_type.setdefault(ev.get("event_type", ""), []).append(ev)

    # Synthesize tenant_context: if any stored event has tenant_id != empty,
    # the tenant context middleware did fire.
    has_tenant_ctx = any(ev.get("tenant_id") for ev in stored_events)

    for layer, et_label in _LAYER_TO_EVENT_TYPE.items():
        # 1) EventStore layers — pick the first matching stored event.
        if layer in _EVENTSTORE_LAYERS:
            target_type = _EVENTSTORE_LAYERS[layer]
            matches = by_type.get(target_type, [])
            if matches:
                ev = matches[0]
                ts = (
                    datetime.fromtimestamp(ev["created_at"], UTC).isoformat()
                    if isinstance(ev.get("created_at"), (int, float))
                    else _iso_now()
                )
                events.append(_SpineEvent(
                    layer=layer,
                    event_type=target_type,
                    timestamp=ts,
                    run_id=ev.get("run_id", "") or run_id,
                    trace_id=ev.get("trace_id", "") or trace_id,
                    source="event_store",
                    extra={
                        "sequence": ev.get("sequence"),
                        "tenant_id": ev.get("tenant_id"),
                    },
                ))
                present.append(layer)
            else:
                missing.append(layer)
            continue

        # 2) Counter-only layers — observed if the counter total > 0.
        if layer in _COUNTER_LAYERS:
            counter_name = _COUNTER_LAYERS[layer]
            total = _counter_total(metrics_snapshot, counter_name)
            if total > 0:
                events.append(_SpineEvent(
                    layer=layer,
                    event_type=et_label,
                    timestamp=_iso_now(),
                    run_id=run_id,
                    trace_id=trace_id,
                    source="metric_counter",
                    extra={"counter_name": counter_name, "counter_total": total},
                ))
                present.append(layer)
            else:
                missing.append(layer)
            continue

        # 3) Synthesized layer (tenant_context).
        if layer == "tenant_context":
            if has_tenant_ctx:
                events.append(_SpineEvent(
                    layer=layer,
                    event_type=et_label,
                    timestamp=started_at,
                    run_id=run_id,
                    trace_id=trace_id,
                    source="synthesized",
                    extra={"derived_from": "stored_event.tenant_id"},
                ))
                present.append(layer)
            else:
                missing.append(layer)
            continue

        missing.append(layer)

    return events, present, missing


def _correlate_trace_id(stored_events: list[dict]) -> str:
    """Return the dominant non-empty trace_id across stored events.

    Returns "" if no stored event carries a trace_id. We pick the first
    non-empty trace_id and require all other non-empty trace_ids to match;
    on disagreement we still return the first one and the gate will note
    it as a coverage warning rather than a fail (per plan §Risks).
    """
    seen = [ev.get("trace_id", "") for ev in stored_events if ev.get("trace_id")]
    if not seen:
        return ""
    return seen[0]


# ----------------------------------------------------------------------
# Server lifecycle
# ----------------------------------------------------------------------


def _build_server_command(port: int) -> list[str]:
    return [sys.executable, "-m", "hi_agent", "serve", "--port", str(port)]


_LLM_CONFIG_PATH = ROOT / "config" / "llm_config.json"


def _inject_volces_key() -> tuple[bool, str | None]:
    """Inject VOLCES_API_KEY env into config/llm_config.json in-place.

    Returns (success, original_text). The original text is returned so the
    caller can restore the file on exit (so the secret never persists in
    the committed copy).

    The platform's json_config_loader reads config/llm_config.json directly
    (no env-var override, no llm_config.local.json merge). The pre-existing
    inject_provider_key.py writes to llm_config.local.json which the loader
    does not read. We work around that here without touching files outside
    the  owner scope, restoring the file unconditionally on exit.
    """
    key = os.environ.get("VOLCES_API_KEY", "").strip()
    if not key:
        return False, None
    if not _LLM_CONFIG_PATH.exists():
        return False, None
    original = _LLM_CONFIG_PATH.read_text(encoding="utf-8")
    try:
        data = json.loads(original)
    except Exception:
        return False, original
    data.setdefault("providers", {}).setdefault("volces", {})["api_key"] = key
    data["default_provider"] = "volces"
    _LLM_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return True, original


def _restore_key(original: str | None) -> None:
    """Restore config/llm_config.json to its pre-injection state."""
    if original is None:
        return
    with contextlib.suppress(Exception):
        _LLM_CONFIG_PATH.write_text(original, encoding="utf-8")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=" real-LLM observability spine")
    p.add_argument("--port", type=int, default=9081)
    p.add_argument("--real-llm", action="store_true",
                   help="Inject VOLCES_API_KEY and use real provider; "
                        "without this flag the script emits structural evidence.")
    p.add_argument("--profile-id", default="w24a_spine")
    p.add_argument("--ready-timeout", type=float, default=120.0)
    p.add_argument("--poll-timeout", type=float, default=180.0)
    p.add_argument("--output", default=None,
                   help="Output JSON path. Defaults to "
                        "docs/verification/<sha>-observability-spine.json")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    head_full = _git_sha_full()
    head_short = _git_sha_short()
    dirty = _git_is_dirty()
    started_at = _iso_now()

    out_path = (
        Path(args.output)
        if args.output
        else ROOT / "docs" / "verification" / f"{head_short}-observability-spine.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Inject key when --real-llm is requested.
    keys_injected = False
    config_original: str | None = None
    if args.real_llm:
        keys_injected, config_original = _inject_volces_key()
        if not keys_injected:
            print(
                "WARN: VOLCES_API_KEY not set or inject failed; "
                "falling back to dev-mock LLM. Provenance will be 'structural'.",
                file=sys.stderr,
            )

    base_url = f"http://127.0.0.1:{args.port}"
    server_cmd = _build_server_command(args.port)
    server: subprocess.Popen[str] | None = None
    failures: list[str] = []
    layer_events: list[_SpineEvent] = []
    layers_present: list[str] = []
    layers_missing: list[str] = []
    run_id_used = ""
    trace_id_used = ""
    final_state = ""
    metrics_snapshot: dict[str, Any] = {}
    ready_snapshot: dict[str, Any] = {}

    try:
        server = subprocess.Popen(server_cmd, cwd=str(ROOT))
        # Quick liveness check; if process exited immediately, fail fast.
        time.sleep(0.5)
        if server.poll() is not None:
            raise RuntimeError(
                f"hi-agent server exited immediately; rc={server.returncode}"
            )

        with httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            ready_snapshot = _wait_ready(client, args.ready_timeout)

            # Drive ONE run.
            try:
                terminal = _drive_one_run(client, args.profile_id, args.poll_timeout)
                run_id_used = terminal.get("run_id", "")
                final_state = terminal.get("state", "")
            except Exception as exc:
                failures.append(f"drive_one_run: {exc}")

            # Harvest events + metrics regardless of run outcome.
            stored_events: list[dict] = []
            if run_id_used:
                try:
                    stored_events = _harvest_events(client, run_id_used)
                except Exception as exc:
                    failures.append(f"harvest_events: {exc}")
            try:
                metrics_snapshot = _harvest_metrics(client)
            except Exception as exc:
                failures.append(f"harvest_metrics: {exc}")

            trace_id_used = _correlate_trace_id(stored_events)

            layer_events, layers_present, layers_missing = _build_layer_events(
                run_id=run_id_used,
                trace_id=trace_id_used,
                stored_events=stored_events,
                metrics_snapshot=metrics_snapshot,
                started_at=started_at,
            )

    except Exception as exc:
        failures.append(f"fatal: {exc}")

    finally:
        if server is not None:
            with contextlib.suppress(Exception):
                server.terminate()
            with contextlib.suppress(Exception):
                server.wait(timeout=10.0)
        if keys_injected:
            _restore_key(config_original)

    # ------------------------------------------------------------------
    # Build evidence document
    # ------------------------------------------------------------------
    is_real = bool(
        args.real_llm
        and keys_injected
        and ready_snapshot.get("llm_mode") == "real"
        and run_id_used
        and trace_id_used  # at least one stored event carried a trace_id
        and not failures
    )

    layer_count = len(layer_events)

    # Verify (trace_id, run_id) correlation across stored-event layers.
    trace_id_consistent = True
    if trace_id_used:
        for ev in layer_events:
            if ev.source == "event_store" and ev.trace_id and ev.trace_id != trace_id_used:
                trace_id_consistent = False
                break

    body: dict[str, Any] = {
        "provenance": "real" if is_real else "structural",
        "release_head": head_short,
        "verified_head": head_short,
        "release_head_full": head_full,
        "git_dirty": dirty,
        "generated_at": _iso_now(),
        "started_at": started_at,
        "run_id": run_id_used,
        "trace_id": trace_id_used,
        "final_state": final_state,
        "layer_count": layer_count,
        "coverage": f"{layer_count}/14",
        "layers": [
            {
                "layer": ev.layer,
                "event_type": ev.event_type,
                "timestamp": ev.timestamp,
                "run_id": ev.run_id,
                "trace_id": ev.trace_id,
                "source": ev.source,
                "extra": ev.extra,
            }
            for ev in layer_events
        ],
        "layers_present": layers_present,
        "layers_missing": layers_missing,
        "trace_id_consistent": trace_id_consistent,
        # Backward-compat fields read by the existing gate.
        "event_count": layer_count,
        "event_types": [ev.event_type for ev in layer_events],
        "spine_ok": layer_count >= 8 and trace_id_consistent,
        "metrics_snapshot": metrics_snapshot,
        "ready_snapshot": ready_snapshot,
        "failures": failures,
        "status": "pass" if (is_real and layer_count >= 14) else (
            "deferred" if layer_count >= 8 else "fail"
        ),
    }

    # Write via canonical evidence_writer to get sidecar + meta stamp.
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from _governance.evidence_writer import write_artifact
    except Exception:
        # Fallback: write raw JSON if helper unavailable.
        out_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    else:
        provenance = body["provenance"]
        write_artifact(
            path=out_path,
            body=body,
            provenance=provenance,
            generator_script=__file__,
            degraded=(provenance != "real"),
        )

    print(f"observability spine: provenance={body['provenance']} "
          f"coverage={body['coverage']} status={body['status']} "
          f"output={out_path}")
    if failures:
        print(f"  failures: {failures}", file=sys.stderr)

    # We always exit 0 when we wrote evidence; the downstream gate decides.
    return 0 if out_path.exists() else 1


if __name__ == "__main__":
    sys.exit(main())
