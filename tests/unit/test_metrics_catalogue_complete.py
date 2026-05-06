"""Unit tests: assert all W12-G metric names are registered in _METRIC_DEFS
and that no forbidden high-cardinality labels appear in the metric catalogue.

Layer 1 — Unit (no external dependencies; reads only in-process catalogue).
"""
from __future__ import annotations

from hi_agent.observability.collector import _METRIC_DEFS

_FORBIDDEN_LABELS = frozenset({
    "run_id", "task_id", "goal", "prompt", "content", "raw_user_input",
})

# Full set of W12-G metric names that survived the W35 hidden-H4 orphan
# audit (2026-05-06). Eleven entries (5 plural-form run-lifecycle counters
# and 6 run/tool latency histograms) were deleted from _METRIC_DEFS because
# they had no production emitter — the singular hi_agent_run_*_total family
# (RunEventEmitter) and the runs_total{status=...} counter superseded them.
# See _W35_DELETED_ORPHAN_NAMES below for the regression guard.
_W12G_EXPECTED_NAMES: frozenset[str] = frozenset({
    # counters
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
})

_W12G_COUNTER_NAMES: frozenset[str] = frozenset({
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

# Histograms: zero W12-G histograms survived the W35 orphan audit. Future
# histograms (e.g. real run duration distribution) require a producer at
# landing time per the W35 hidden-H4 policy in
# hi_agent/observability/ARCHITECTURE.md.
_W12G_HISTOGRAM_NAMES: frozenset[str] = frozenset()

# Names deleted under W35 hidden-H4 corrective: 5 plural-form run lifecycle
# counters and 6 run/tool latency histograms had no producer in
# hi_agent/, agent_server/, agent_kernel/, or scripts/ at deletion time.
# The regression guard test_w35_deleted_orphans_stay_deleted asserts these
# names do NOT reappear in _METRIC_DEFS without a producer.
_W35_DELETED_ORPHAN_NAMES: frozenset[str] = frozenset({
    "hi_agent_runs_started_total",
    "hi_agent_runs_completed_total",
    "hi_agent_runs_failed_total",
    "hi_agent_runs_cancelled_total",
    "hi_agent_runs_timed_out_total",
    "hi_agent_run_duration_seconds",
    "hi_agent_run_no_progress_seconds",
    "hi_agent_queue_claim_latency_seconds",
    "hi_agent_tool_latency_seconds",
    "hi_agent_human_gate_age_seconds",
    "hi_agent_drain_duration_seconds",
})


class TestW12GMetricNamesRegistered:
    """Surviving W12-G metric names must remain present in _METRIC_DEFS."""

    def test_all_expected_names_present(self) -> None:
        """Every surviving W12-G metric name appears as a key in _METRIC_DEFS."""
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
        """18 W12-G metrics survived the W35 hidden-H4 orphan audit."""
        assert len(_W12G_EXPECTED_NAMES) == 18


class TestW35OrphanMetricsStayDeleted:
    """Regression guard for the W35 hidden-H4 orphan-metric corrective.

    Eleven W12-G declarations (5 plural run-lifecycle counters and
    6 run/tool latency histograms) were deleted because they had no
    producer. They MUST NOT reappear in ``_METRIC_DEFS`` without a
    matching emitter — that would re-introduce the silent contract-claim
    drift (Rule 14) the corrective closed.
    """

    def test_deleted_orphans_absent_from_metric_defs(self) -> None:
        """Each deleted orphan name remains absent from _METRIC_DEFS."""
        registered = set(_METRIC_DEFS.keys())
        resurrected = _W35_DELETED_ORPHAN_NAMES & registered
        assert not resurrected, (
            "W35 hidden-H4 orphan metrics resurrected without a producer: "
            f"{sorted(resurrected)}. If you need one of these metrics, add "
            "the emitter call-site in the same commit and update "
            "hi_agent/observability/ARCHITECTURE.md 'Orphan-metric audit' "
            "section."
        )

    def test_runs_started_total_specifically_absent(self) -> None:
        """Spot-check: hi_agent_runs_started_total is the canonical W35 example."""
        assert "hi_agent_runs_started_total" not in _METRIC_DEFS


_WAVE13_I3_I7_EXPECTED_NAMES: frozenset[str] = frozenset({
    # I-3: EventBus sync observer drop counter (Rule 7 alarm)
    "hi_agent_event_bus_observer_drop_total",
    # I-7a: DLQ dead-letter counter (Rule 7 alarm)
    "hi_agent_runs_dead_lettered_total",
    # I-7b: duplicate claim blocked counter (Rule 7 alarm)
    "hi_agent_queue_duplicate_claim_blocked_total",
})


class TestWave13I3I7MetricNamesRegistered:
    """Wave 13 I-3 / I-7 Rule 7 alarm counters must be present in _METRIC_DEFS."""

    def test_all_expected_names_present(self) -> None:
        """Every Wave 13 I-3/I-7 metric name appears as a key in _METRIC_DEFS."""
        registered = set(_METRIC_DEFS.keys())
        missing = _WAVE13_I3_I7_EXPECTED_NAMES - registered
        assert not missing, f"Missing Wave 13 I-3/I-7 metrics: {sorted(missing)}"

    def test_all_are_counters(self) -> None:
        """All Wave 13 I-3/I-7 metrics have kind='counter'."""
        for name in _WAVE13_I3_I7_EXPECTED_NAMES:
            defn = _METRIC_DEFS[name]
            assert defn.kind == "counter", (
                f"{name}: expected kind='counter', got {defn.kind!r}"
            )

    def test_help_text_non_empty(self) -> None:
        """Every Wave 13 I-3/I-7 metric has a non-empty help_text."""
        for name in _WAVE13_I3_I7_EXPECTED_NAMES:
            defn = _METRIC_DEFS[name]
            assert defn.help_text, f"{name}: help_text must not be empty"


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
