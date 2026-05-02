"""Tests for MetricsCollector including counters, gauges, histograms, and alerts."""

from __future__ import annotations

import threading

from hi_agent.observability.collector import (
    AlertRule,
    MetricsCollector,
    default_alert_rules,
)


class TestMetricsCollectorBasics:
    """Counter, gauge, histogram basics."""

    def test_counter_increment(self):
        mc = MetricsCollector()
        mc.record("runs_total", 1.0, {"status": "completed"})
        mc.record("runs_total", 1.0, {"status": "completed"})
        snap = mc.snapshot()
        assert snap["runs_total"]['status="completed"'] == 2.0

    def test_gauge_set_and_up_down(self):
        mc = MetricsCollector()
        mc.gauge_set("runs_active", 5.0)
        snap = mc.snapshot()
        assert snap["runs_active"]["_total"] == 5.0

        mc.increment("runs_active", 3.0)
        snap = mc.snapshot()
        assert snap["runs_active"]["_total"] == 8.0

        mc.increment("runs_active", -2.0)
        snap = mc.snapshot()
        assert snap["runs_active"]["_total"] == 6.0

    def test_histogram_percentiles(self):
        mc = MetricsCollector()
        for v in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            mc.record("llm_latency_seconds", v)
        snap = mc.snapshot()
        hist = snap["llm_latency_seconds"]["_total"]
        assert hist["count"] == 10
        assert hist["p50"] > 0
        assert hist["p95"] > 0
        assert hist["p99"] > 0
        assert hist["p95"] >= hist["p50"]

    def test_snapshot_empty(self):
        mc = MetricsCollector()
        snap = mc.snapshot()
        assert isinstance(snap, dict)
        # snapshot() auto-populates process-level gauges (thread_count, open_fd_count)
        # via sample_process_metrics(); no user-recorded metrics should be present.
        _auto_keys = {"hi_agent_thread_count", "hi_agent_open_fd_count"}
        user_metrics = {k: v for k, v in snap.items() if k not in _auto_keys}
        assert len(user_metrics) == 0

    def test_prometheus_text_format(self):
        mc = MetricsCollector()
        mc.record("runs_total", 3.0, {"status": "completed"})
        mc.record("llm_latency_seconds", 1.5)
        text = mc.to_prometheus_text()
        assert "# TYPE runs_total counter" in text
        assert "runs_total" in text
        assert "# TYPE llm_latency_seconds summary" in text
        assert text.endswith("\n")

    def test_thread_safety(self):
        mc = MetricsCollector()
        errors = []

        def writer(tid: int):
            try:
                for i in range(100):
                    mc.record("runs_total", 1.0, {"status": "completed"})
                    mc.record("llm_latency_seconds", 0.01 * i)
                    mc.gauge_set("runs_active", float(tid))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        snap = mc.snapshot()
        assert snap["runs_total"]['status="completed"'] == 400.0

    def test_unknown_metric_ignored(self):
        mc = MetricsCollector()
        mc.record("nonexistent_metric", 42.0)
        snap = mc.snapshot()
        assert "nonexistent_metric" not in snap


class TestAlertRules:
    """Alert subsystem tests."""

    def test_alert_fires(self):
        mc = MetricsCollector()
        rule = AlertRule(
            name="test_alert",
            metric_name="runs_total",
            threshold=5.0,
            comparator="gt",
            labels={"status": "failed"},
            cooldown_s=0.0,
        )
        mc.add_alert_rule(rule)
        for _ in range(6):
            mc.record("runs_total", 1.0, {"status": "failed"})
        alerts = mc.check_alerts()
        assert len(alerts) == 1
        assert alerts[0].rule_name == "test_alert"
        assert alerts[0].current_value == 6.0

    def test_cooldown_respected(self):
        mc = MetricsCollector()
        rule = AlertRule(
            name="cool_rule",
            metric_name="runs_total",
            threshold=0.0,
            comparator="gt",
            labels={"status": "failed"},
            cooldown_s=100.0,
        )
        mc.add_alert_rule(rule)
        mc.record("runs_total", 1.0, {"status": "failed"})
        alerts1 = mc.check_alerts()
        assert len(alerts1) == 1
        alerts2 = mc.check_alerts()
        assert len(alerts2) == 0

    def test_callback_invoked(self):
        mc = MetricsCollector()
        captured = []
        mc.set_alert_callback(captured.append)
        rule = AlertRule(
            name="cb_rule",
            metric_name="runs_total",
            threshold=0.0,
            comparator="gt",
            cooldown_s=0.0,
        )
        mc.add_alert_rule(rule)
        mc.record("runs_total", 5.0)
        mc.check_alerts()
        assert len(captured) == 1
        assert captured[0].rule_name == "cb_rule"

    def test_alert_history(self):
        mc = MetricsCollector()
        rule = AlertRule(
            name="hist_rule",
            metric_name="runs_total",
            threshold=0.0,
            comparator="gt",
            cooldown_s=0.0,
        )
        mc.add_alert_rule(rule)
        mc.record("runs_total", 1.0)
        mc.check_alerts()
        mc.check_alerts()
        history = mc.get_alert_history()
        assert len(history) == 2

    def test_auto_check_alerts(self):
        captured = []
        mc = MetricsCollector(auto_check_alerts=True)
        mc.set_alert_callback(captured.append)
        rule = AlertRule(
            name="auto_rule",
            metric_name="runs_total",
            threshold=2.0,
            comparator="gt",
            cooldown_s=0.0,
        )
        mc.add_alert_rule(rule)
        mc.record("runs_total", 3.0)
        assert len(captured) == 1

    def test_default_alert_rules(self):
        rules = default_alert_rules()
        assert len(rules) == 3
        names = {r.name for r in rules}
        assert "high_error_rate" in names
        assert "high_latency" in names
        assert "budget_warning" in names
