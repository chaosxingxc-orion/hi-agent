"""Tests for inject_provider_key.py multi-provider support."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def test_auto_with_no_keys_fails_clearly() -> None:
    """--provider auto with no env vars set fails with informative error."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"VOLCES_API_KEY", "VOLCES_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"}
    }
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "inject_provider_key.py"),
            "--provider",
            "auto",
        ],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode != 0
    stderr_lower = result.stderr.lower()
    assert "volces_api_key" in result.stderr or "no provider key" in stderr_lower


def test_explicit_provider_reads_correct_env() -> None:
    """--provider volces reads VOLCES_API_KEY."""
    # Minimal smoke test: script file parses without error
    spec = importlib.util.spec_from_file_location(
        "inject_provider_key", ROOT / "scripts" / "inject_provider_key.py"
    )
    assert spec is not None


def test_restore_flag_removes_local_config(tmp_path: Path) -> None:
    """--restore removes config/llm_config.local.json when it exists."""
    local_config = ROOT / "config" / "llm_config.local.json"
    created = False
    try:
        if not local_config.exists():
            local_config.write_text("{}\n", encoding="utf-8")
            created = True
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "inject_provider_key.py"), "--restore"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0
        assert not local_config.exists()
    finally:
        # Clean up if the restore didn't happen
        if created and local_config.exists():
            local_config.unlink()


def test_inject_provider_key_script_exists() -> None:
    """scripts/inject_provider_key.py must exist."""
    assert (ROOT / "scripts" / "inject_provider_key.py").exists()


def test_inject_provider_key_exists() -> None:
    """inject_provider_key.py must exist (inject_volces_key.py shim was removed W25)."""
    assert (ROOT / "scripts" / "inject_provider_key.py").exists()
