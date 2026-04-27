"""Unit tests: assert all W12-G metric names are registered in _METRIC_DEFS
and that no forbidden high-cardinality labels appear in the metric catalogue.

Layer 1 — Unit (no external dependencies; reads only in-process catalogue).
"""
from __future__ import annotations

from hi_agent.observability.collector import _METRIC_DEFS

_FORBIDDEN_LABELS = frozenset({
    "run_id", "task_id", "goal", "prompt", "content", "raw_user_input",
})

# Full set of metric names added in W12-G.
_W12G_EXPECTED_NAMES: frozenset[str] = frozenset({
    # counters
    "hi_agent_runs_started_total",
    "hi_agent_runs_completed_total",
    "hi_agent_runs_failed_total",
    "hi_agent_runs_cancelled_total",
    "hi_agent_runs_timed_out_total",
    "hi_agent_queue_lease_renew_total",
    "hi_agent_queue_expired_lease_total",
    "hi_agent_queue_duplicate_claim_blocked_total",
    "hi_agent_admission_rejected_total",
    "hi_agent_recovery_triggered_total",
    "hi_agent_recovery_success_total",
    "hi_agent_recovery_failed_total",
    "hi_agent_mcp_crash_total",
    "hi_agent_tool_calls_total",
    "hi_agent_human_gate_open_total",
    "hi_agent_runs_recovered_after_restart_total",
    "hi_agent_runs_dead_lettered_total",
    # gauges
    "hi_agent_runs_stalled",
    "hi_agent_queue_depth",
    "hi_agent_queue_oldest_age_seconds",
    "hi_agent_dlq_depth",
    "hi_agent_dlq_oldest_age_seconds",
    "hi_agent_active_runs_at_drain",
    # histograms
    "hi_agent_run_duration_seconds",
    "hi_agent_run_no_progress_seconds",
    "hi_agent_queue_claim_latency_seconds",
    "hi_agent_tool_latency_seconds",
    "hi_agent_human_gate_age_seconds",
    "hi_agent_drain_duration_seconds",
})

_W12G_COUNTER_NAMES: frozenset[str] = frozenset({
    "hi_agent_runs_started_total",
    "hi_agent_runs_completed_total",
    "hi_agent_runs_failed_total",
    "hi_agent_runs_cancelled_total",
    "hi_agent_runs_timed_out_total",
    "hi_agent_queue_lease_renew_total",
    "hi_agent_queue_expired_lease_total",
    "hi_agent_queue_duplicate_claim_blocked_total",
    "hi_agent_admission_rejected_total",
    "hi_agent_recovery_triggered_total",
    "hi_agent_recovery_success_total",
    "hi_agent_recovery_failed_total",
    "hi_agent_mcp_crash_total",
    "hi_agent_tool_calls_total",
    "hi_agent_human_gate_open_total",
    "hi_agent_runs_recovered_after_restart_total",
    "hi_agent_runs_dead_lettered_total",
})

_W12G_GAUGE_NAMES: frozenset[str] = frozenset({
    "hi_agent_runs_stalled",
    "hi_agent_queue_depth",
    "hi_agent_queue_oldest_age_seconds",
    "hi_agent_dlq_depth",
    "hi_agent_dlq_oldest_age_seconds",
    "hi_agent_active_runs_at_drain",
})

_W12G_HISTOGRAM_NAMES: frozenset[str] = frozenset({
    "hi_agent_run_duration_seconds",
    "hi_agent_run_no_progress_seconds",
    "hi_agent_queue_claim_latency_seconds",
    "hi_agent_tool_latency_seconds",
    "hi_agent_human_gate_age_seconds",
    "hi_agent_drain_duration_seconds",
})


class TestW12GMetricNamesRegistered:
    """All 29 W12-G metric names must be present in _METRIC_DEFS."""

    def test_all_expected_names_present(self) -> None:
        """Every W12-G metric name appears as a key in _METRIC_DEFS."""
        registered = set(_METRIC_DEFS.keys())
        missing = _W12G_EXPECTED_NAMES - registered
        assert not missing, f"Missing W12-G metrics: {sorted(missing)}"

    def test_counter_kind(self) -> None:
        """All W12-G counter metrics have kind='counter'."""
        for name in _W12G_COUNTER_NAMES:
            defn = _METRIC_DEFS[name]
            assert defn.kind == "counter", (
                f"{name}: expected kind='counter', got {defn.kind!r}"
            )

    def test_gauge_kind(self) -> None:
        """All W12-G gauge metrics have kind='gauge'."""
        for name in _W12G_GAUGE_NAMES:
            defn = _METRIC_DEFS[name]
            assert defn.kind == "gauge", (
                f"{name}: expected kind='gauge', got {defn.kind!r}"
            )

    def test_histogram_kind(self) -> None:
        """All W12-G histogram metrics have kind='histogram'."""
        for name in _W12G_HISTOGRAM_NAMES:
            defn = _METRIC_DEFS[name]
            assert defn.kind == "histogram", (
                f"{name}: expected kind='histogram', got {defn.kind!r}"
            )

    def test_help_text_non_empty(self) -> None:
        """Every W12-G metric has a non-empty help_text."""
        for name in _W12G_EXPECTED_NAMES:
            defn = _METRIC_DEFS[name]
            assert defn.help_text, f"{name}: help_text must not be empty"

    def test_total_count(self) -> None:
        """Exactly 29 W12-G metrics are expected."""
        assert len(_W12G_EXPECTED_NAMES) == 29


class TestMetricsCardinalityNoBannedSegments:
    """No registered metric name may embed a forbidden high-cardinality token
    as a name segment (e.g. 'metric_run_id_total' would be a violation).
    """

    def test_no_forbidden_label_segments_in_names(self) -> None:
        """Metric names must not contain forbidden high-cardinality tokens."""
        violations: list[tuple[str, str]] = []
        for metric_name in _METRIC_DEFS:
            segments = set(metric_name.split("_"))
            for forbidden in _FORBIDDEN_LABELS:
                if forbidden in segments:
                    violations.append((metric_name, forbidden))
        assert not violations, (
            "Metrics with forbidden high-cardinality tokens in name: "
            + str(violations)
        )
