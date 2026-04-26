"""Unit tests for hi_agent.config.posture_guards (Wave 10.3 W3-A)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from hi_agent.config.posture import Posture
from hi_agent.config.posture_guards import require_spine, require_tenant


class TestRequireTenantDev:
    """dev posture: empty tenant_id is admitted with a warning."""

    def test_empty_returns_empty_string(self):
        p = Posture.DEV
        result = require_tenant("", where="test_site", posture=p)
        assert result == ""

    def test_none_returns_empty_string(self):
        p = Posture.DEV
        result = require_tenant(None, where="test_site", posture=p)
        assert result == ""

    def test_empty_logs_warning(self, caplog):
        import logging

        p = Posture.DEV
        with caplog.at_level(logging.WARNING, logger="hi_agent.config.posture_guards"):
            require_tenant(None, where="my_call_site", posture=p)
        assert "my_call_site" in caplog.text

    def test_non_empty_returned_unchanged(self):
        p = Posture.DEV
        result = require_tenant("tenant-123", where="test_site", posture=p)
        assert result == "tenant-123"


class TestRequireTenantStrict:
    """research and prod postures: empty tenant_id raises ValueError."""

    @pytest.mark.parametrize("posture", [Posture.RESEARCH, Posture.PROD])
    def test_empty_raises(self, posture):
        with pytest.raises(ValueError, match="empty tenant_id"):
            require_tenant("", where="test_strict_site", posture=posture)

    @pytest.mark.parametrize("posture", [Posture.RESEARCH, Posture.PROD])
    def test_none_raises(self, posture):
        with pytest.raises(ValueError, match="empty tenant_id"):
            require_tenant(None, where="test_strict_site", posture=posture)

    @pytest.mark.parametrize("posture", [Posture.RESEARCH, Posture.PROD])
    def test_non_empty_returned_unchanged(self, posture):
        result = require_tenant("t-abc", where="test_strict_site", posture=posture)
        assert result == "t-abc"


class TestRequireSpine:
    """require_spine validates both tenant_id and project_id."""

    def test_dev_both_empty_returns_empty_pair(self):
        p = Posture.DEV
        tid, pid = require_spine(tenant_id=None, project_id=None, where="spine_test", posture=p)
        assert tid == ""
        assert pid == ""

    def test_dev_both_populated_returned_unchanged(self):
        p = Posture.DEV
        tid, pid = require_spine(tenant_id="t1", project_id="p1", where="spine_test", posture=p)
        assert tid == "t1"
        assert pid == "p1"

    def test_research_empty_project_raises(self):
        p = Posture.RESEARCH
        with pytest.raises(ValueError, match="empty tenant_id"):
            require_spine(tenant_id="t1", project_id="", where="spine_test", posture=p)

    def test_research_empty_tenant_raises(self):
        p = Posture.RESEARCH
        with pytest.raises(ValueError, match="empty tenant_id"):
            require_spine(tenant_id=None, project_id="p1", where="spine_test", posture=p)


class TestRequireTenantCounterIncrement:
    """dev admit increments the observability counter (best-effort)."""

    def test_counter_increment_called_on_dev_admit(self):
        mock_collector = MagicMock()
        mock_get = MagicMock(return_value=mock_collector)
        p = Posture.DEV
        # get_metrics_collector is imported lazily inside require_tenant;
        # patch at source module and also create the name in posture_guards namespace.
        with patch("hi_agent.observability.collector.get_metrics_collector", mock_get), patch(
            "hi_agent.config.posture_guards.get_metrics_collector",
            mock_get,
            create=True,
        ):
            require_tenant(None, where="counter_test", posture=p)
        mock_collector.increment.assert_called_once()
        call_args = mock_collector.increment.call_args
        assert "hi_agent_empty_tenant_admit_total" in call_args[0]
