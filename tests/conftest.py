"""Pytest global test environment configuration."""

from __future__ import annotations

import os

# Prevent accidentally-added root-level test_*.py files from being collected.
# All tests must live in tests/unit/, tests/integration/, or tests/e2e/.
collect_ignore_glob = ["test_*.py"]

# Tests run in non-prod mode so strict production fail-fast gates do not
# block deterministic local/in-process test execution.
os.environ.setdefault("HI_AGENT_ENV", "dev")

# Only enable heuristic fallback when not running the "release" test profile.
# The release profile must exercise strict paths without heuristic fallback.
_test_profile = os.environ.get("HI_AGENT_TEST_PROFILE", "")
if _test_profile != "release":
    os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")
