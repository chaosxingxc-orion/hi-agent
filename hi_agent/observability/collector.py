"""Structured metrics collector with thread-safe counters, gauges, and histograms.

Provides Prometheus exposition format export and JSON snapshots without any
external dependencies.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from math import ceil
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _MetricDef:
    """Internal metric definition."""

    name: str
    kind: str  # "counter", "gauge", "histogram"
    help_text: str = ""


# Pre-defined metric catalogue.
_METRIC_DEFS: dict[str, _MetricDef] = {
    "runs_total": _MetricDef("runs_total", "counter", "Total runs by status."),
    "runs_active": _MetricDef("runs_active", "gauge", "Currently active runs."),
    "llm_calls_total": _MetricDef("llm_calls_total", "counter", "Total LLM calls by tier."),
    "llm_tokens_total": _MetricDef("llm_tokens_total", "counter", "Total LLM tokens by direction."),
    "llm_latency_seconds": _MetricDef(
        "llm_latency_seconds",
        "histogram",
        "LLM call latency in seconds.",
    ),
    "actions_total": _MetricDef(
        "actions_total", "counter", "Total actions by effect class and status."
    ),
    "stage_duration_seconds": _MetricDef(
        "stage_duration_seconds",
        "histogram",
        "Stage execution duration in seconds.",
    ),
    "memory_retrievals_total": _MetricDef(
        "memory_retrievals_total", "counter", "Total memory retrieval operations."
    ),
    "skill_invocations_total": _MetricDef(
        "skill_invocations_total",
        "counter",
        "Total skill invocations by skill_id and outcome.",
    ),
    "llm_cost_usd_total": _MetricDef(
        "llm_cost_usd_total",
        "counter",
        "Cumulative USD spend on LLM calls.",
    ),
    "llm_cost_per_run": _MetricDef(
        "llm_cost_per_run",
        "histogram",
        "Per-run LLM cost distribution in USD.",
    ),
    # Rule 8 / Rule 15: every outgoing LLM request increments this counter.
    # Exposed as ``hi_agent_llm_requests_total`` in /metrics output.
    # Gateway code calls record_llm_request() from hi_agent.observability.fallback.
    "hi_agent_llm_requests_total": _MetricDef(
        "hi_agent_llm_requests_total",
        "counter",
        "Total outgoing LLM requests by provider, model, and tier.",
    ),
    # Rule 14: fallback / degradation signals. Any code path that substitutes
    # a heuristic or degraded result for a primary path MUST record one of
    # these counters so Rule 15's operator-shape gate is not vacuous.
    "fallback_llm": _MetricDef(
        "fallback_llm",
        "counter",
        "LLM call fell back to a degraded path (retries exhausted, gateway missing, etc.).",
    ),
    "fallback_heuristic": _MetricDef(
        "fallback_heuristic",
        "counter",
        "A subsystem produced a heuristic result in place of a model/tool call.",
    ),
    "fallback_capability": _MetricDef(
        "fallback_capability",
        "counter",
        "A capability handler returned a heuristic/degraded result.",
    ),
    "fallback_route": _MetricDef(
        "fallback_route",
        "counter",
        "Route engine fell back to a default route (rule miss, LLM router failure).",
    ),
    # Rule 7: system-scope fallback counter for events not tied to any run.
    # Incremented when record_fallback() is called with run_id="system".
    "hi_agent_fallback_no_run_scope_total": _MetricDef(
        "hi_agent_fallback_no_run_scope_total",
        "counter",
        "Fallback events recorded with run_id='system' (no run scope).",
    ),
    # TE-1: corrupt lines encountered while loading the artifact ledger.
    "hi_agent_artifact_corrupt_line_total": _MetricDef(
        "hi_agent_artifact_corrupt_line_total",
        "counter",
        "Corrupt lines skipped while loading the artifact ledger JSONL file.",
    ),
    # Rule 7: Retry-After header parse failure in failover chain.
    "hi_agent_retry_after_parse_total": _MetricDef(
        "hi_agent_retry_after_parse_total",
        "counter",
        "Retry-After header present but not parseable as float (Rule 7 alarm).",
    ),
    # Rule 7: MCP subprocess stderr tail read failure.
    "hi_agent_mcp_stderr_tail_failure_total": _MetricDef(
        "hi_agent_mcp_stderr_tail_failure_total",
        "counter",
        "MCP transport get_stderr_tail() raised unexpectedly (Rule 7 alarm).",
    ),
    # B2: stderr-reader thread join timeout (FD leak signal).
    "hi_agent_mcp_thread_join_timeout_total": _MetricDef(
        "hi_agent_mcp_thread_join_timeout_total",
        "counter",
        "MCP stderr-reader threads that did not exit within 5s on close() (Rule 7 alarm).",
    ),
    # B4: per-failure-code counter (labels: failure_code).
    "hi_agent_failure_total": _MetricDef(
        "hi_agent_failure_total",
        "counter",
        "Failures classified by FailureCode taxonomy (Rule 7 alarm; labels: failure_code).",
    ),
    # B6: LLM token counter with tenant_bucket dimension (labels: direction, tenant_bucket).
    # tenant_bucket = str(hash(tenant_id) % 16) keeps cardinality bounded to 16 buckets.
    "hi_agent_llm_tokens_total": _MetricDef(
        "hi_agent_llm_tokens_total",
        "counter",
        "Total LLM tokens by direction and tenant bucket (labels: direction, tenant_bucket).",
    ),
    # Rule 7 alarm for recovery reenqueue disabled under strict posture.
    "hi_agent_recovery_reenqueue_disabled_total": _MetricDef(
        "hi_agent_recovery_reenqueue_disabled_total",
        "counter",
        "Recovery reenqueue suppressed by opt-out flag under research/prod (Rule 7 alarm).",
    ),
    # TE-4: per-kind Prometheus counters required by Rule 7.
    # Incremented by record_fallback() in addition to the generic fallback_<kind>
    # counters so that /metrics exposes the canonical Rule-7 names.
    "hi_agent_llm_fallback_total": _MetricDef(
        "hi_agent_llm_fallback_total",
        "counter",
        "LLM fallback events (Rule 7 gate counter).",
    ),
    "hi_agent_heuristic_fallback_total": _MetricDef(
        "hi_agent_heuristic_fallback_total",
        "counter",
        "Heuristic fallback events (Rule 7 gate counter).",
    ),
    "hi_agent_capability_fallback_total": _MetricDef(
        "hi_agent_capability_fallback_total",
        "counter",
        "Capability fallback events (Rule 7 gate counter).",
    ),
    "hi_agent_route_fallback_total": _MetricDef(
        "hi_agent_route_fallback_total",
        "counter",
        "Route fallback events (Rule 7 gate counter).",
    ),
    # Legacy fallback taxonomy counters (kept for backward-compatibility with
    # existing record_fallback() call-sites in context/, llm/, runner_stage/).
    # These predate the four-kind taxonomy but are retained so that their
    # signals are countable instead of silently dropped.
    "fallback_expected_degradation": _MetricDef(
        "fallback_expected_degradation", "counter", "Expected degradation event."
    ),
    "fallback_unexpected_exception": _MetricDef(
        "fallback_unexpected_exception", "counter", "Unexpected exception caught and swallowed."
    ),
    "fallback_security_denied": _MetricDef(
        "fallback_security_denied", "counter", "Security policy denied an action; fallback taken."
    ),
    "fallback_dependency_unavailable": _MetricDef(
        "fallback_dependency_unavailable",
        "counter",
        "External dependency unavailable; degraded path taken.",
    ),
    "fallback_heuristic_fallback": _MetricDef(
        "fallback_heuristic_fallback", "counter", "Heuristic used in place of primary logic."
    ),
    "fallback_policy_bypass_dev": _MetricDef(
        "fallback_policy_bypass_dev",
        "counter",
        "Dev-mode policy bypass (must be zero in prod releases).",
    ),
    # KG backend override alarm — incremented when HI_AGENT_KG_BACKEND=json
    # is accepted under research posture (Rule 7 alarm; rejected under prod).
    "hi_agent_kg_backend_override_total": _MetricDef(
        "hi_agent_kg_backend_override_total",
        "counter",
        "KG backend overridden away from posture default (Rule 7 alarm).",
    ),
    # Rule 7 closure on LLM hot path — event-bus publish failures
    # (labels: gateway, run_id_present). Incremented when the gateway tries
    # to publish an llm_call event to the EventBus and the publish raises.
    # Replaces a previously-silent ``except Exception: pass`` in the
    # ``HttpLLMGateway.complete`` boundary.
    "hi_agent_event_bus_publish_errors_total": _MetricDef(
        "hi_agent_event_bus_publish_errors_total",
        "counter",
        "EventBus.publish raised on LLM-call boundary (Rule 7 alarm; "
        "labels: gateway, run_id_present).",
    ),
    # Rule 7 closure on LLM hot path — record_fallback recording
    # failures (labels: gateway, original_reason). Incremented when the
    # gateway invokes ``record_fallback`` on a fallback branch and the
    # recorder itself raises. Without this counter the original fallback
    # reason was muted, defeating Rule 7's "alarm bell" requirement.
    "hi_agent_fallback_recording_errors_total": _MetricDef(
        "hi_agent_fallback_recording_errors_total",
        "counter",
        "record_fallback raised inside the gateway fallback branch (Rule 7 "
        "alarm; labels: gateway, original_reason).",
    ),
    # Run lifecycle counters (labels: tenant_id, outcome, reason).
    "hi_agent_runs_started_total": _MetricDef(
        "hi_agent_runs_started_total",
        "counter",
        "Total run execution starts.",
    ),
    "hi_agent_runs_completed_total": _MetricDef(
        "hi_agent_runs_completed_total",
        "counter",
        "Total run completions.",
    ),
    "hi_agent_runs_failed_total": _MetricDef(
        "hi_agent_runs_failed_total",
        "counter",
        "Total run failures.",
    ),
    "hi_agent_runs_cancelled_total": _MetricDef(
        "hi_agent_runs_cancelled_total",
        "counter",
        "Total run cancellations.",
    ),
    "hi_agent_runs_timed_out_total": _MetricDef(
        "hi_agent_runs_timed_out_total",
        "counter",
        "Total run timeouts.",
    ),
    # Queue operation counters (labels: outcome).
    "hi_agent_queue_lease_renew_total": _MetricDef(
        "hi_agent_queue_lease_renew_total",
        "counter",
        "Lease renewal attempts.",
    ),
    "hi_agent_queue_expired_lease_total": _MetricDef(
        "hi_agent_queue_expired_lease_total",
        "counter",
        "Expired leases reclaimed.",
    ),
    "hi_agent_queue_duplicate_claim_blocked_total": _MetricDef(
        "hi_agent_queue_duplicate_claim_blocked_total",
        "counter",
        "Duplicate claim attempts blocked.",
    ),
    # Admission and recovery counters (labels: reason).
    "hi_agent_admission_rejected_total": _MetricDef(
        "hi_agent_admission_rejected_total",
        "counter",
        "Run admission rejections.",
    ),
    "hi_agent_recovery_triggered_total": _MetricDef(
        "hi_agent_recovery_triggered_total",
        "counter",
        "Recovery attempts triggered.",
    ),
    "hi_agent_recovery_success_total": _MetricDef(
        "hi_agent_recovery_success_total",
        "counter",
        "Recovery successes.",
    ),
    "hi_agent_recovery_failed_total": _MetricDef(
        "hi_agent_recovery_failed_total",
        "counter",
        "Recovery failures.",
    ),
    # MCP and tool counters (labels: server, tool, outcome).
    "hi_agent_mcp_crash_total": _MetricDef(
        "hi_agent_mcp_crash_total",
        "counter",
        "MCP subprocess crashes.",
    ),
    "hi_agent_tool_calls_total": _MetricDef(
        "hi_agent_tool_calls_total",
        "counter",
        "Tool call attempts.",
    ),
    "hi_agent_human_gate_open_total": _MetricDef(
        "hi_agent_human_gate_open_total",
        "counter",
        "Human gate open events.",
    ),
    "hi_agent_runs_recovered_after_restart_total": _MetricDef(
        "hi_agent_runs_recovered_after_restart_total",
        "counter",
        "Runs recovered after worker restart.",
    ),
    "hi_agent_runs_dead_lettered_total": _MetricDef(
        "hi_agent_runs_dead_lettered_total",
        "counter",
        "Runs moved to DLQ.",
    ),
    # Run and queue gauges.
    "hi_agent_runs_stalled": _MetricDef(
        "hi_agent_runs_stalled",
        "gauge",
        "Runs with no progress for >120s.",
    ),
    "hi_agent_queue_depth": _MetricDef(
        "hi_agent_queue_depth",
        "gauge",
        "Current queue depth.",
    ),
    "hi_agent_queue_oldest_age_seconds": _MetricDef(
        "hi_agent_queue_oldest_age_seconds",
        "gauge",
        "Age of oldest queued item.",
    ),
    "hi_agent_dlq_depth": _MetricDef(
        "hi_agent_dlq_depth",
        "gauge",
        "Dead letter queue depth.",
    ),
    "hi_agent_dlq_oldest_age_seconds": _MetricDef(
        "hi_agent_dlq_oldest_age_seconds",
        "gauge",
        "Age of oldest DLQ item.",
    ),
    "hi_agent_active_runs_at_drain": _MetricDef(
        "hi_agent_active_runs_at_drain",
        "gauge",
        "Active runs when drain initiated.",
    ),
    # I-3 / Rule 7: sync observer drops in EventBus.
    "hi_agent_event_bus_observer_drop_total": _MetricDef(
        "hi_agent_event_bus_observer_drop_total",
        "counter",
        "Sync observer calls that raised an exception (Rule 7 alarm).",
    ),
    # Rule 7: event buffering overflow / flush failure signal.
    "hi_agent_event_buffer_overflow_total": _MetricDef(
        "hi_agent_event_buffer_overflow_total",
        "counter",
        "Event buffer flush failures or capacity overflow signals (Rule 7 alarm).",
    ),
    # I-8 / Rule 7: generic silent-degradation events recorded via helper.
    "hi_agent_silent_degradation_total": _MetricDef(
        "hi_agent_silent_degradation_total",
        "counter",
        "Silent-degradation events recorded via record_silent_degradation() (Rule 7).",
    ),
    # I-5 / Rule 7: watchdog scan errors in HeartbeatWatchdog.
    "hi_agent_watchdog_scan_failed_total": _MetricDef(
        "hi_agent_watchdog_scan_failed_total",
        "counter",
        "Watchdog scan errors in HeartbeatWatchdog (Rule 7 alarm).",
    ),
    # Rule 7: background scheduler failures in MemoryLifecycleManager.
    "hi_agent_dream_scheduler_errors_total": _MetricDef(
        "hi_agent_dream_scheduler_errors_total",
        "counter",
        "Dream / consolidation scheduler exceptions (Rule 7 alarm).",
    ),
    # I-6 / Rule 7: reconcile-loop DLQ error metric.
    "hi_agent_reconcile_dlq_error_total": _MetricDef(
        "hi_agent_reconcile_dlq_error_total",
        "counter",
        "Reconcile loop DLQ-depth read errors (Rule 7 alarm).",
    ),
    # I-1 / Rule 7: run lease lost due to heartbeat renewal failure.
    "hi_agent_runtime_lease_lost_total": _MetricDef(
        "hi_agent_runtime_lease_lost_total",
        "counter",
        "Run lease lost due to heartbeat renewal failure (Rule 7 alarm).",
    ),
    # Rule 7: lease renewal / heartbeat failures.
    "hi_agent_lease_renew_errors_total": _MetricDef(
        "hi_agent_lease_renew_errors_total",
        "counter",
        "Lease renewal exceptions in the run heartbeat loop (Rule 7 alarm).",
    ),
    # Run and tool histograms (labels: tenant_id, outcome, tool).
    "hi_agent_run_duration_seconds": _MetricDef(
        "hi_agent_run_duration_seconds",
        "histogram",
        "End-to-end run duration.",
    ),
    "hi_agent_run_no_progress_seconds": _MetricDef(
        "hi_agent_run_no_progress_seconds",
        "histogram",
        "Duration of no-progress gaps.",
    ),
    "hi_agent_queue_claim_latency_seconds": _MetricDef(
        "hi_agent_queue_claim_latency_seconds",
        "histogram",
        "Queue claim latency.",
    ),
    "hi_agent_tool_latency_seconds": _MetricDef(
        "hi_agent_tool_latency_seconds",
        "histogram",
        "Tool call latency.",
    ),
    "hi_agent_human_gate_age_seconds": _MetricDef(
        "hi_agent_human_gate_age_seconds",
        "histogram",
        "Human gate pending duration.",
    ),
    "hi_agent_drain_duration_seconds": _MetricDef(
        "hi_agent_drain_duration_seconds",
        "histogram",
        "Graceful drain duration.",
    ),
    # J1: request body too-large rejections (Rule 7: countable security signal).
    "hi_agent_request_too_large_total": _MetricDef(
        "hi_agent_request_too_large_total",
        "counter",
        "Requests rejected because a body field exceeded the size limit.",
    ),
    # Wave 17 Theme C: observability spine new counters.
    # http_request: incremented by TraceIdMiddleware for every HTTP request received.
    "hi_agent_http_requests_total": _MetricDef(
        "hi_agent_http_requests_total",
        "counter",
        "Total HTTP requests received by the server (method + path labels).",
    ),
    # Rule 7: health-check subcomponent failures.
    "hi_agent_health_check_errors_total": _MetricDef(
        "hi_agent_health_check_errors_total",
        "counter",
        "Health check subcomponent exceptions (labels: check_name).",
    ),
    # event_stored: incremented by SQLiteEventStore for every event appended.
    "hi_agent_events_stored_total": _MetricDef(
        "hi_agent_events_stored_total",
        "counter",
        "Total events written to the durable SQLiteEventStore.",
    ),
    # metric_emitted: incremented by _publish_run_event in RunManager.
    "hi_agent_events_published_total": _MetricDef(
        "hi_agent_events_published_total",
        "counter",
        "Total lifecycle events published via _publish_run_event in RunManager.",
    ),
    # Rule 7: publish-side observability failures.
    "hi_agent_event_publish_errors_total": _MetricDef(
        "hi_agent_event_publish_errors_total",
        "counter",
        "Failures while recording run lifecycle publish metrics (Rule 7 alarm).",
    ),
    # Rule 7: run execution exceptions swallowed by RunManager.
    "hi_agent_run_execution_errors_total": _MetricDef(
        "hi_agent_run_execution_errors_total",
        "counter",
        "Exceptions raised while executing a run task (Rule 7 alarm).",
    ),
    # H2: subprocess zombie prevention — incremented when proc.wait(timeout=5)
    # fails after terminate(), meaning the OS must reap the process eventually.
    "hi_agent_subprocess_zombie_total": _MetricDef(
        "hi_agent_subprocess_zombie_total",
        "counter",
        "Subprocess terminate() calls where wait(timeout=5) timed out (potential zombie).",
    ),
    # H3: process-level resource gauges, sampled on each /metrics scrape.
    "hi_agent_open_fd_count": _MetricDef(
        "hi_agent_open_fd_count",
        "gauge",
        "Number of open file descriptors in the current process (psutil; skipped on Windows).",
    ),
    "hi_agent_thread_count": _MetricDef(
        "hi_agent_thread_count",
        "gauge",
        "Number of active threads in the current process (threading.active_count()).",
    ),
    # AX-G: recurrence-ledger TBD-resolved counters (7 governance gate metrics).
    "hi_agent_clean_env_freshness_failures_total": _MetricDef(
        "hi_agent_clean_env_freshness_failures_total",
        "counter",
        "Counts clean-env freshness gate failures.",
    ),
    "hi_agent_observability_spine_structural_total": _MetricDef(
        "hi_agent_observability_spine_structural_total",
        "counter",
        "Counts spine layers with non-real provenance.",
    ),
    "hi_agent_chaos_not_runtime_coupled_total": _MetricDef(
        "hi_agent_chaos_not_runtime_coupled_total",
        "counter",
        "Counts chaos scenarios not runtime-coupled.",
    ),
    "hi_agent_score_cap_overstatement_total": _MetricDef(
        "hi_agent_score_cap_overstatement_total",
        "counter",
        "Counts score cap overstatement events.",
    ),
    "hi_agent_missing_owner_tag_total": _MetricDef(
        "hi_agent_missing_owner_tag_total",
        "counter",
        "Counts commits missing owner track tag.",
    ),
    "hi_agent_cross_tenant_allowlist_expiry_total": _MetricDef(
        "hi_agent_cross_tenant_allowlist_expiry_total",
        "counter",
        "Counts expiring cross-tenant allowlist entries.",
    ),
    "hi_agent_test_theatre_detected_total": _MetricDef(
        "hi_agent_test_theatre_detected_total",
        "counter",
        "Counts test-theatre patterns detected by CI.",
    ),
    # AX-G: orphan-resolved counters (3 metrics referenced in ledger but not in _METRIC_DEFS).
    "hi_agent_manifest_freshness_violations_total": _MetricDef(
        "hi_agent_manifest_freshness_violations_total",
        "counter",
        "Counts manifest freshness violations.",
    ),
    "hi_agent_soak_evidence_age_hours": _MetricDef(
        "hi_agent_soak_evidence_age_hours",
        "gauge",
        "Age in hours of most recent soak evidence.",
    ),
    "hi_agent_release_gate_continue_on_error_total": _MetricDef(
        "hi_agent_release_gate_continue_on_error_total",
        "counter",
        "Counts release gate steps that used continue-on-error.",
    ),
    # AX-A4: observability spine layer counters.
    # hi_agent_spine_llm_call_total: incremented by emit_llm_call() on every
    # LLM completion dispatch (both sync HttpLLMGateway and async HTTPGateway,
    # and HTTPStreamingGateway). Labels: profile.
    "hi_agent_spine_llm_call_total": _MetricDef(
        "hi_agent_spine_llm_call_total",
        "counter",
        "Spine layer: total LLM completion dispatches (labels: profile).",
    ),
    # hi_agent_spine_tool_call_total: incremented by emit_tool_call() on every
    # action dispatch in ActionDispatcher (attempt==1 boundary). Labels: tool, profile.
    "hi_agent_spine_tool_call_total": _MetricDef(
        "hi_agent_spine_tool_call_total",
        "counter",
        "Spine layer: total tool execution dispatches (labels: tool, profile).",
    ),
    # hi_agent_spine_heartbeat_renewed_total: incremented by emit_heartbeat_renewed()
    # in the lease heartbeat loop of RunManager when heartbeat() returns True.
    "hi_agent_spine_heartbeat_renewed_total": _MetricDef(
        "hi_agent_spine_heartbeat_renewed_total",
        "counter",
        "Spine layer: total successful run lease heartbeat renewals.",
    ),
    # hi_agent_spine_trace_id_propagated_total: incremented by
    # emit_trace_id_propagated() in TraceIdMiddleware after each HTTP request
    # that extracts or mints a trace_id.
    "hi_agent_spine_trace_id_propagated_total": _MetricDef(
        "hi_agent_spine_trace_id_propagated_total",
        "counter",
        "Spine layer: total trace_id propagations through HTTP middleware.",
    ),
    # w25-F: 8 new spine layer counters for previously unwired layers.
    "hi_agent_spine_run_manager_total": _MetricDef(
        "hi_agent_spine_run_manager_total",
        "counter",
        "Spine layer: total run_queued events (run_manager boundary).",
    ),
    "hi_agent_spine_tenant_context_total": _MetricDef(
        "hi_agent_spine_tenant_context_total",
        "counter",
        "Spine layer: total per-request tenant context resolutions (tenant_context boundary).",
    ),
    "hi_agent_spine_reasoning_loop_total": _MetricDef(
        "hi_agent_spine_reasoning_loop_total",
        "counter",
        "Spine layer: total reasoning-loop stage entries (reasoning_loop boundary).",
    ),
    "hi_agent_spine_capability_handler_total": _MetricDef(
        "hi_agent_spine_capability_handler_total",
        "counter",
        "Spine layer: total capability handler dispatches (capability_handler boundary).",
    ),
    "hi_agent_spine_sync_bridge_total": _MetricDef(
        "hi_agent_spine_sync_bridge_total",
        "counter",
        "Spine layer: total sync→async bridge dispatches (sync_bridge boundary).",
    ),
    "hi_agent_spine_http_transport_total": _MetricDef(
        "hi_agent_spine_http_transport_total",
        "counter",
        "Spine layer: total outbound HTTP transport requests (http_transport boundary).",
    ),
    "hi_agent_spine_artifact_ledger_total": _MetricDef(
        "hi_agent_spine_artifact_ledger_total",
        "counter",
        "Spine layer: total artifact registrations in ArtifactLedger (artifact_ledger boundary).",
    ),
    "hi_agent_spine_event_store_total": _MetricDef(
        "hi_agent_spine_event_store_total",
        "counter",
        "Spine layer: total events persisted to SQLiteEventStore (event_store boundary).",
    ),
}

# Maximum samples retained for histogram-like metrics.
_HISTOGRAM_MAX_SAMPLES = 1000


@dataclass(frozen=True)
class AlertRule:
    """Definition of a threshold-based alert rule."""

    name: str
    metric_name: str
    threshold: float
    comparator: str = "gt"  # gt, gte, lt, lte, eq
    labels: dict[str, str] | None = None
    cooldown_s: float = 60.0


@dataclass(frozen=True)
class Alert:
    """A fired alert instance."""

    rule_name: str
    metric_name: str
    current_value: float
    threshold: float
    timestamp: float
    labels: dict[str, str] = field(default_factory=dict)


def default_alert_rules() -> list[AlertRule]:
    """Return a set of sensible default alert rules."""
    return [
        AlertRule(
            name="high_error_rate",
            metric_name="runs_total",
            threshold=10.0,
            comparator="gt",
            labels={"status": "failed"},
            cooldown_s=300.0,
        ),
        AlertRule(
            name="high_latency",
            metric_name="llm_latency_seconds",
            threshold=30.0,
            comparator="gt",
            cooldown_s=300.0,
        ),
        AlertRule(
            name="budget_warning",
            metric_name="llm_cost_usd_total",
            threshold=100.0,
            comparator="gt",
            cooldown_s=600.0,
        ),
    ]


def _strict_metrics_enabled() -> bool:
    """Return True if ``HI_AGENT_STRICT_METRICS`` selects strict mode."""
    return os.environ.get("HI_AGENT_STRICT_METRICS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _report_unknown_metric(metric_name: str, op: str) -> None:
    """Log an ERROR (and optionally raise) when an unknown metric name is used.

    Rule 14 forbids silently dropping fallback/degradation signals.  Any caller
    writing to a metric name that is not registered in ``_METRIC_DEFS`` has a
    wiring bug that must be visible.  In normal mode we log loudly and return.
    In strict mode (``HI_AGENT_STRICT_METRICS=1``) we raise ``KeyError`` so
    tests can assert on the defect.
    """
    known = sorted(_METRIC_DEFS.keys())
    _logger.error(
        "MetricsCollector.%s received unknown metric name %r (known=%s). "
        "This signal is being dropped — register the metric in _METRIC_DEFS.",
        op,
        metric_name,
        known,
    )
    if _strict_metrics_enabled():
        raise KeyError(f"unknown metric: {metric_name!r}")


def _labels_key(labels: dict[str, str] | None) -> str:
    """Produce a canonical string key for a label set."""
    if not labels:
        return ""
    return ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))


def _prom_labels(labels: dict[str, str] | None) -> str:
    """Format labels for Prometheus exposition text."""
    key = _labels_key(labels)
    return f"{{{key}}}" if key else ""


class MetricsCollector:
    """Thread-safe metrics collector.

    Supports three metric kinds:

    * **counter** -- monotonically increasing value per label-set.
    * **gauge** -- value that can go up and down per label-set.
    * **histogram** -- stores the last *N* observed values and computes
      percentiles on read (p50 / p95 / p99).

    All public methods are protected by a single :class:`threading.Lock`.
    """

    def __init__(
        self,
        *,
        histogram_max_samples: int = _HISTOGRAM_MAX_SAMPLES,
        auto_check_alerts: bool = False,
    ) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[str, float]] = {}
        self._gauges: dict[str, dict[str, float]] = {}
        self._histograms: dict[str, dict[str, deque[float]]] = {}
        self._histogram_max = histogram_max_samples
        self._auto_check_alerts = auto_check_alerts
        self._alert_rules: dict[str, AlertRule] = {}
        self._alert_callback: Any = None
        self._alert_history: list[Alert] = []
        self._alert_last_fired: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        metric_name: str,
        value: float = 1.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Record a metric observation.

        For counters, *value* is added to the current total.
        For gauges, *value* replaces the current reading.
        For histograms, *value* is appended to the sample window.

        Unknown metric names are logged at ERROR level so that mis-wired
        signals surface loudly instead of being silently dropped (Rule 14).
        Set ``HI_AGENT_STRICT_METRICS=1`` to raise ``KeyError`` instead.
        """
        defn = _METRIC_DEFS.get(metric_name)
        if defn is None:
            _report_unknown_metric(metric_name, "record")
            return
        lk = _labels_key(labels)
        with self._lock:
            if defn.kind == "counter":
                bucket = self._counters.setdefault(metric_name, {})
                bucket[lk] = bucket.get(lk, 0.0) + value
            elif defn.kind == "gauge":
                bucket = self._gauges.setdefault(metric_name, {})
                bucket[lk] = value
            elif defn.kind == "histogram":
                bucket = self._histograms.setdefault(metric_name, {})
                dq = bucket.setdefault(lk, deque(maxlen=self._histogram_max))
                dq.append(value)
        if self._auto_check_alerts:
            self.check_alerts()

    def increment(
        self,
        metric_name: str,
        value: float = 1.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Convenience alias: increment a counter or gauge by *value*.

        Unknown metric names are logged at ERROR level (Rule 14: signals must
        not be silently dropped). When ``HI_AGENT_STRICT_METRICS=1`` the call
        raises ``KeyError`` so mis-wired call-sites fail loudly in tests.
        """
        defn = _METRIC_DEFS.get(metric_name)
        if defn is None:
            _report_unknown_metric(metric_name, "increment")
            return
        lk = _labels_key(labels)
        with self._lock:
            if defn.kind == "counter":
                bucket = self._counters.setdefault(metric_name, {})
                bucket[lk] = bucket.get(lk, 0.0) + value
            elif defn.kind == "gauge":
                bucket = self._gauges.setdefault(metric_name, {})
                bucket[lk] = bucket.get(lk, 0.0) + value

    def gauge_set(
        self,
        metric_name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Set a gauge to an absolute value."""
        defn = _METRIC_DEFS.get(metric_name)
        if defn is None:
            _report_unknown_metric(metric_name, "gauge_set")
            return
        if defn.kind != "gauge":
            return
        lk = _labels_key(labels)
        with self._lock:
            bucket = self._gauges.setdefault(metric_name, {})
            bucket[lk] = value

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def sample_process_metrics(self) -> None:
        """Sample process-level resource gauges (H3).

        Called before each /metrics scrape so hi_agent_open_fd_count and
        hi_agent_thread_count reflect current process state without a background timer.
        """
        import sys as _sys
        import threading as _threading
        self.gauge_set("hi_agent_thread_count", float(_threading.active_count()))
        if _sys.platform != "win32":
            try:
                import psutil  # type: ignore[import-untyped]  # expiry_wave: Wave 28
                self.gauge_set("hi_agent_open_fd_count", float(psutil.Process().num_fds()))
            except Exception as exc:
                _logger.warning("collector.sample_process_metrics: psutil fd count failed: %s", exc)

    def snapshot(self) -> dict[str, Any]:
        """Return all current metric values as a JSON-friendly dict."""
        self.sample_process_metrics()
        with self._lock:
            result: dict[str, Any] = {}

            for name, bucket in self._counters.items():
                result[name] = self._snapshot_labeled(bucket)

            for name, bucket in self._gauges.items():
                result[name] = self._snapshot_labeled(bucket)

            for name, bucket in self._histograms.items():
                hist_out: dict[str, Any] = {}
                for lk, dq in bucket.items():
                    samples = sorted(dq)
                    entry: dict[str, Any] = {
                        "count": len(samples),
                        "sum": sum(samples),
                    }
                    if samples:
                        entry["p50"] = self._percentile(samples, 0.50)
                        entry["p95"] = self._percentile(samples, 0.95)
                        entry["p99"] = self._percentile(samples, 0.99)
                    label_key = lk if lk else "_total"
                    hist_out[label_key] = entry
                result[name] = hist_out

            return result

    def to_prometheus_text(self) -> str:
        """Return all metrics in Prometheus exposition format (text/plain)."""
        self.sample_process_metrics()
        lines: list[str] = []
        with self._lock:
            # Counters
            for name, bucket in sorted(self._counters.items()):
                defn = _METRIC_DEFS.get(name)
                if defn:
                    lines.append(f"# HELP {name} {defn.help_text}")
                    lines.append(f"# TYPE {name} counter")
                for lk, val in sorted(bucket.items()):
                    prom_lbl = f"{{{lk}}}" if lk else ""
                    lines.append(f"{name}{prom_lbl} {val}")

            # Gauges
            for name, bucket in sorted(self._gauges.items()):
                defn = _METRIC_DEFS.get(name)
                if defn:
                    lines.append(f"# HELP {name} {defn.help_text}")
                    lines.append(f"# TYPE {name} gauge")
                for lk, val in sorted(bucket.items()):
                    prom_lbl = f"{{{lk}}}" if lk else ""
                    lines.append(f"{name}{prom_lbl} {val}")

            # Histograms (expose as summary-style with count/sum/quantiles)
            for name, bucket in sorted(self._histograms.items()):
                defn = _METRIC_DEFS.get(name)
                if defn:
                    lines.append(f"# HELP {name} {defn.help_text}")
                    lines.append(f"# TYPE {name} summary")
                for lk, dq in sorted(bucket.items()):
                    samples = sorted(dq)
                    prom_lbl_base = lk
                    if samples:
                        for q, tag in [
                            (0.5, "0.5"),
                            (0.95, "0.95"),
                            (0.99, "0.99"),
                        ]:
                            qlbl = (
                                f'{{quantile="{tag}",{prom_lbl_base}}}'
                                if prom_lbl_base
                                else f'{{quantile="{tag}"}}'
                            )
                            lines.append(f"{name}{qlbl} {self._percentile(samples, q)}")
                    count_lbl = f"{{{prom_lbl_base}}}" if prom_lbl_base else ""
                    lines.append(f"{name}_count{count_lbl} {len(samples)}")
                    lines.append(f"{name}_sum{count_lbl} {sum(samples)}")

        # Prometheus expects a trailing newline.
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _snapshot_labeled(bucket: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for lk, val in bucket.items():
            label_key = lk if lk else "_total"
            out[label_key] = val
        return out

    # ------------------------------------------------------------------
    # Alert subsystem
    # ------------------------------------------------------------------

    def add_alert_rule(self, rule: AlertRule) -> None:
        """Register an alert rule."""
        with self._lock:
            self._alert_rules[rule.name] = rule

    def set_alert_callback(self, callback: Any) -> None:
        """Set a callable invoked for each fired alert."""
        with self._lock:
            self._alert_callback = callback

    def check_alerts(self) -> list[Alert]:
        """Evaluate all alert rules against current metric values.

        Returns a list of :class:`Alert` instances for rules whose
        conditions are met and whose cooldown has expired.
        """
        now = time.time()
        fired: list[Alert] = []
        with self._lock:
            for rule in self._alert_rules.values():
                value = self._read_metric_value(rule.metric_name, rule.labels)
                if value is None:
                    continue
                if not self._compare(value, rule.threshold, rule.comparator):
                    continue
                last = self._alert_last_fired.get(rule.name, 0.0)
                if now - last < rule.cooldown_s:
                    continue
                alert = Alert(
                    rule_name=rule.name,
                    metric_name=rule.metric_name,
                    current_value=value,
                    threshold=rule.threshold,
                    timestamp=now,
                    labels=dict(rule.labels) if rule.labels else {},
                )
                fired.append(alert)
                self._alert_history.append(alert)
                self._alert_last_fired[rule.name] = now
                if self._alert_callback is not None:
                    self._alert_callback(alert)
        return fired

    def get_alert_history(self) -> list[Alert]:
        """Return all previously fired alerts."""
        with self._lock:
            return list(self._alert_history)

    @property
    def completed_run_count(self) -> int:
        """Return the cumulative number of completed runs recorded so far.

        Reads the ``runs_total`` counter filtered to ``status=completed``
        label entries and returns their sum as an integer.  Falls back to
        summing all ``runs_total`` label buckets when no completed-specific
        entry is present.
        """
        with self._lock:
            bucket = self._counters.get("runs_total", {})
            if not bucket:
                return 0
            # Prefer the explicit completed-status bucket.
            for lk, val in bucket.items():
                if 'status="completed"' in lk or "status=completed" in lk:
                    return int(val)
            # Fall back to total across all statuses.
            return int(sum(bucket.values()))

    # ------------------------------------------------------------------
    # Alert internals
    # ------------------------------------------------------------------

    def _read_metric_value(self, metric_name: str, labels: dict[str, str] | None) -> float | None:
        """Read a single metric value under lock (caller holds lock)."""
        lk = _labels_key(labels)
        if metric_name in self._counters:
            return self._counters[metric_name].get(lk)
        if metric_name in self._gauges:
            return self._gauges[metric_name].get(lk)
        if metric_name in self._histograms:
            dq = self._histograms[metric_name].get(lk)
            if dq:
                samples = sorted(dq)
                return self._percentile(samples, 0.95)
        return None

    @staticmethod
    def _compare(value: float, threshold: float, comparator: str) -> bool:
        if comparator == "gt":
            return value > threshold
        if comparator == "gte":
            return value >= threshold
        if comparator == "lt":
            return value < threshold
        if comparator == "lte":
            return value <= threshold
        if comparator == "eq":
            return value == threshold
        return False

    @staticmethod
    def _percentile(sorted_samples: list[float], q: float) -> float:
        """Nearest-rank percentile over a pre-sorted list."""
        n = len(sorted_samples)
        if n == 0:
            return 0.0
        rank = ceil(q * n)
        return sorted_samples[max(0, rank - 1)]


# ----------------------------------------------------------------------
# Process-level singleton
# ----------------------------------------------------------------------
#
# ``record_fallback`` needs access to a shared MetricsCollector even when
# called from deeply-nested code paths that were not given an explicit
# injection.  Callers that build their own collector should register it
# here via :func:`set_metrics_collector` so fallback signals are countable.

_SINGLETON_LOCK = threading.Lock()
_SINGLETON: MetricsCollector | None = None


def set_metrics_collector(collector: MetricsCollector | None) -> None:
    """Register a process-wide default MetricsCollector.

    Passing ``None`` clears the registration (primarily for test isolation).
    """
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = collector


def get_metrics_collector() -> MetricsCollector | None:
    """Return the process-wide MetricsCollector, or ``None`` if unset."""
    with _SINGLETON_LOCK:
        return _SINGLETON
