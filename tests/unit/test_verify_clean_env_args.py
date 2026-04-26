"""Unit tests for verify_clean_env.py CLI arg parsing and env-var precedence.

Layer 1 — Unit: tests _parse_args() and _resolve_dir() in isolation.
No external network; no subprocess calls to pytest.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Ensure scripts/ is importable
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_clean_env import ROOT as SCRIPT_ROOT
from scripts.verify_clean_env import _resolve_dir


class TestResolveDir:
    """Tests for the CLI > env var > tempfile priority chain."""

    def test_cli_arg_wins(self) -> None:
        """--basetemp /tmp/foo sets basetemp to /tmp/foo."""
        result = _resolve_dir("/tmp/foo", "HI_AGENT_PYTEST_TEMPROOT", "hi_agent_pytest_")
        assert result == "/tmp/foo"

    def test_env_var_used_when_no_cli(self) -> None:
        """HI_AGENT_PYTEST_TEMPROOT=/tmp/bar is used when no CLI arg given."""
        with patch.dict(os.environ, {"HI_AGENT_PYTEST_TEMPROOT": "/tmp/bar"}):
            result = _resolve_dir(None, "HI_AGENT_PYTEST_TEMPROOT", "hi_agent_pytest_")
        assert result == "/tmp/bar"

    def test_cli_overrides_env_var(self) -> None:
        """CLI arg takes priority over env var."""
        with patch.dict(os.environ, {"HI_AGENT_PYTEST_TEMPROOT": "/tmp/bar"}):
            result = _resolve_dir("/tmp/cli", "HI_AGENT_PYTEST_TEMPROOT", "hi_agent_pytest_")
        assert result == "/tmp/cli"

    def test_default_uses_tempdir_not_repo_internal(self) -> None:
        """When neither CLI nor env var is set, basetemp is under system tempdir."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove env var if present
            env_without = {k: v for k, v in os.environ.items()
                           if k != "HI_AGENT_PYTEST_TEMPROOT"}
            with patch.dict(os.environ, env_without, clear=True):
                result = _resolve_dir(None, "HI_AGENT_PYTEST_TEMPROOT", "hi_agent_pytest_")

        # Must NOT be inside the repo root
        assert not result.startswith(str(SCRIPT_ROOT)), (
            f"Default basetemp {result!r} must not be inside repo root {SCRIPT_ROOT}"
        )
        # Must be under system tempdir
        system_tmp = tempfile.gettempdir()
        assert result.startswith(system_tmp), (
            f"Expected {result!r} to start with system tempdir {system_tmp!r}"
        )

    def test_cache_dir_env_var_precedence(self) -> None:
        """HI_AGENT_PYTEST_CACHE_DIR env var is used for cache_dir when no CLI arg."""
        with patch.dict(os.environ, {"HI_AGENT_PYTEST_CACHE_DIR": "/tmp/my_cache"}):
            result = _resolve_dir(None, "HI_AGENT_PYTEST_CACHE_DIR", "hi_agent_cache_")
        assert result == "/tmp/my_cache"
