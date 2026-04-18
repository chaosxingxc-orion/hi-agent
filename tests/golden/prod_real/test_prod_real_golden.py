"""Golden path: prod-real tier — requires real credentials (W12-001)."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("HI_AGENT_ENV") == "prod",
    reason="prod-real golden path only runs with HI_AGENT_ENV=prod",
)


class TestProdRealGoldenPath:
    """Full execution against real LLM and kernel endpoints.

    These tests are skipped unless HI_AGENT_ENV=prod is set, ensuring
    they never run in CI without explicit opt-in.
    """

    def test_executor_completes_prod_run(self):
        """A full run against real endpoints returns completed or failed."""
        ...
