"""Golden path: local-real tier — uses fake HTTP servers (W12-001)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="requires fake_llm_server fixture — W11-002 pending integration")


class TestLocalRealGoldenPath:
    """Full execution with fake LLM and fake kernel HTTP servers."""

    def test_executor_uses_real_gateway_path(self, fake_llm_base_url):
        """Executor wired to a fake LLM HTTP server completes a run."""
        ...

    def test_kernel_http_mode_resolves(self, fake_kernel_base_url):
        """Executor wired to a fake kernel HTTP server resolves a run."""
        ...
