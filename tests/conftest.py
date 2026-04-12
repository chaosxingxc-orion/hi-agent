"""Pytest global test environment configuration."""

from __future__ import annotations

import os

# Tests run in non-prod mode so strict production fail-fast gates do not
# block deterministic local/in-process test execution.
os.environ.setdefault("HI_AGENT_ENV", "dev")
os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")
