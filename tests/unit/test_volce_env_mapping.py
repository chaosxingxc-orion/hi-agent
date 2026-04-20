"""Regression tests for Volce credential mapping in CI."""

from __future__ import annotations

import os
import subprocess
import sys

from tests.conftest import _set_env_if_blank


def test_set_env_if_blank_replaces_empty_secret(monkeypatch):
    """Blank env vars should be treated as missing."""
    monkeypatch.setenv("HI_AGENT_TEST_EMPTY_SECRET", "")

    _set_env_if_blank("HI_AGENT_TEST_EMPTY_SECRET", "volce-key")

    assert os.environ["HI_AGENT_TEST_EMPTY_SECRET"] == "volce-key"


def test_set_env_if_blank_preserves_non_empty_secret(monkeypatch):
    """Existing real secrets must never be overwritten by Volce fallback mapping."""
    monkeypatch.setenv("HI_AGENT_TEST_REAL_SECRET", "real-key")

    _set_env_if_blank("HI_AGENT_TEST_REAL_SECRET", "volce-key")

    assert os.environ["HI_AGENT_TEST_REAL_SECRET"] == "real-key"


def test_conftest_maps_volce_when_ci_secrets_are_blank():
    """GitHub Actions blank secrets should not block Volce prod mapping."""
    script = """
import os
os.environ["VOLCE_API_KEY"] = "volce-key"
os.environ["VOLCE_BASE_URL"] = "https://ark.cn-beijing.volces.com/api/coding/v1"
os.environ["OPENAI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
import tests.conftest  # noqa: F401
assert os.environ["OPENAI_API_KEY"] == "volce-key"
assert os.environ["ANTHROPIC_API_KEY"] == "volce-key"
"""

    proc = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
