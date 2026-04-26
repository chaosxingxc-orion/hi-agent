"""Tests that RecoveryAlarm fires under strict posture when reenqueue is disabled.

Rule 7 compliance: every silent-degradation path must be Countable, Attributable,
and Inspectable.  These tests assert the Attributable (WARNING log) dimension.
"""
from __future__ import annotations

import logging
from unittest.mock import patch


class TestNoAlarmUnderDevPosture:
    def test_no_alarm_when_dev_posture_and_reenqueue_disabled(self, monkeypatch):
        """Under dev posture, no alarm even when reenqueue is disabled."""
        monkeypatch.setenv("HI_AGENT_RECOVERY_REENQUEUE", "0")
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

        # Import inside test to pick up monkeypatched env.
        from hi_agent.config.posture import Posture
        from hi_agent.server.recovery import RecoveryAlarm

        with patch.object(logging.getLogger("hi_agent.server.recovery"), "warning") as mock_warn:
            RecoveryAlarm.fire_if_needed("run-dev-1", "tenant-dev", Posture.from_env())
            assert not mock_warn.called, "No WARNING should be emitted under dev posture."


class TestAlarmFiresUnderResearchPosture:
    def test_alarm_fires_when_research_and_reenqueue_disabled(self, monkeypatch):
        """Under research posture with reenqueue disabled, WARNING must be logged."""
        monkeypatch.setenv("HI_AGENT_RECOVERY_REENQUEUE", "0")
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")

        from hi_agent.config.posture import Posture
        from hi_agent.server.recovery import RecoveryAlarm

        with patch.object(
            logging.getLogger("hi_agent.server.recovery"), "warning"
        ) as mock_warn:
            RecoveryAlarm.fire_if_needed("run-123", "tenant-abc", Posture.from_env())

        assert mock_warn.called, "WARNING must be emitted under research posture."
        call_args_str = str(mock_warn.call_args)
        assert "run-123" in call_args_str or "%s" in call_args_str

    def test_alarm_fires_when_prod_and_reenqueue_disabled(self, monkeypatch):
        """Under prod posture with reenqueue disabled, WARNING must be logged."""
        monkeypatch.setenv("HI_AGENT_RECOVERY_REENQUEUE", "0")
        monkeypatch.setenv("HI_AGENT_POSTURE", "prod")

        from hi_agent.config.posture import Posture
        from hi_agent.server.recovery import RecoveryAlarm

        with patch.object(
            logging.getLogger("hi_agent.server.recovery"), "warning"
        ) as mock_warn:
            RecoveryAlarm.fire_if_needed("run-prod-1", "tenant-prod", Posture.from_env())

        assert mock_warn.called, "WARNING must be emitted under prod posture."


class TestNoAlarmWhenReenqueueEnabled:
    def test_no_alarm_when_reenqueue_enabled_default(self, monkeypatch):
        """When reenqueue is enabled (default), no alarm even under research posture."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        monkeypatch.delenv("HI_AGENT_RECOVERY_REENQUEUE", raising=False)

        from hi_agent.config.posture import Posture
        from hi_agent.server.recovery import RecoveryAlarm

        with patch.object(
            logging.getLogger("hi_agent.server.recovery"), "warning"
        ) as mock_warn:
            RecoveryAlarm.fire_if_needed("run-123", "tenant-abc", Posture.from_env())
            assert not mock_warn.called, "No alarm when reenqueue is enabled."

    def test_no_alarm_when_reenqueue_explicitly_1(self, monkeypatch):
        """When HI_AGENT_RECOVERY_REENQUEUE=1 explicitly, no alarm under research."""
        monkeypatch.setenv("HI_AGENT_RECOVERY_REENQUEUE", "1")
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")

        from hi_agent.config.posture import Posture
        from hi_agent.server.recovery import RecoveryAlarm

        with patch.object(
            logging.getLogger("hi_agent.server.recovery"), "warning"
        ) as mock_warn:
            RecoveryAlarm.fire_if_needed("run-123", "tenant-abc", Posture.from_env())
            assert not mock_warn.called


class TestCountableMetricIncrement:
    def test_counter_incremented_under_research_and_opt_out(self, monkeypatch):
        """Rule 7 Countable: the named Prometheus counter increments when alarm fires."""
        monkeypatch.setenv("HI_AGENT_RECOVERY_REENQUEUE", "0")
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")

        from hi_agent.config.posture import Posture
        from hi_agent.observability.collector import MetricsCollector, set_metrics_collector
        from hi_agent.server.recovery import RecoveryAlarm

        collector = MetricsCollector()
        set_metrics_collector(collector)
        try:
            RecoveryAlarm.fire_if_needed("run-ctr-1", "tenant-ctr", Posture.from_env())
            snapshot = collector.snapshot()
            counter_val = snapshot.get("hi_agent_recovery_reenqueue_disabled_total", {}).get(
                "_total", 0
            )
            assert counter_val >= 1, (
                "hi_agent_recovery_reenqueue_disabled_total must be incremented on alarm."
            )
        finally:
            set_metrics_collector(None)

    def test_counter_not_incremented_under_dev(self, monkeypatch):
        """Counter must stay at zero when posture is dev."""
        monkeypatch.setenv("HI_AGENT_RECOVERY_REENQUEUE", "0")
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

        from hi_agent.config.posture import Posture
        from hi_agent.observability.collector import MetricsCollector, set_metrics_collector
        from hi_agent.server.recovery import RecoveryAlarm

        collector = MetricsCollector()
        set_metrics_collector(collector)
        try:
            RecoveryAlarm.fire_if_needed("run-dev-ctr", "tenant-dev", Posture.from_env())
            snapshot = collector.snapshot()
            counter_val = snapshot.get("hi_agent_recovery_reenqueue_disabled_total", {}).get(
                "_total", 0
            )
            assert counter_val == 0
        finally:
            set_metrics_collector(None)
