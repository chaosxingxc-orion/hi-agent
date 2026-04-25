"""Integration test for `hi-agent init` CLI subcommand (DX-1).

Layer 3 (E2E): drives through the CLI public interface and verifies
observable file-system outputs. No mocks on the subsystem under test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_cli_init_research_creates_files(tmp_path: Path) -> None:
    """Running `hi-agent init --posture research` creates the expected files with valid JSON."""
    config_dir = tmp_path / "my_config"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hi_agent",
            "init",
            "--posture",
            "research",
            "--config-dir",
            str(config_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"init exited non-zero: {result.stderr}"

    # Verify expected files exist
    assert (config_dir / "hi_agent_config.json").exists(), "hi_agent_config.json missing"
    assert (config_dir / "profiles" / "research.json").exists(), "profiles/research.json missing"
    assert (config_dir / ".env.example").exists(), ".env.example missing"

    # Verify hi_agent_config.json is valid JSON
    cfg = json.loads((config_dir / "hi_agent_config.json").read_text(encoding="utf-8"))
    assert isinstance(cfg, dict), "hi_agent_config.json root must be a dict"
    assert "run_manager" in cfg, "hi_agent_config.json must contain run_manager key"

    # Verify profiles/research.json is valid JSON with profile_id
    profile = json.loads((config_dir / "profiles" / "research.json").read_text(encoding="utf-8"))
    assert isinstance(profile, dict), "profiles/research.json root must be a dict"
    assert profile.get("profile_id") == "research", "profile_id must be 'research'"


def test_cli_init_dev_creates_files(tmp_path: Path) -> None:
    """Running `hi-agent init --posture dev` creates the expected files."""
    config_dir = tmp_path / "dev_config"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hi_agent",
            "init",
            "--posture",
            "dev",
            "--config-dir",
            str(config_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"init exited non-zero: {result.stderr}"
    assert (config_dir / "hi_agent_config.json").exists()
    assert (config_dir / "profiles" / "dev.json").exists()


def test_cli_init_prod_creates_files(tmp_path: Path) -> None:
    """Running `hi-agent init --posture prod` creates the expected files."""
    config_dir = tmp_path / "prod_config"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hi_agent",
            "init",
            "--posture",
            "prod",
            "--config-dir",
            str(config_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"init exited non-zero: {result.stderr}"
    assert (config_dir / "hi_agent_config.json").exists()
    assert (config_dir / "profiles" / "prod.json").exists()


def test_cli_init_idempotent(tmp_path: Path) -> None:
    """Running `hi-agent init` twice does not overwrite existing files."""
    config_dir = tmp_path / "idempotent_config"

    for _ in range(2):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "hi_agent",
                "init",
                "--posture",
                "research",
                "--config-dir",
                str(config_dir),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    # File contents are still valid JSON after double run
    cfg = json.loads((config_dir / "hi_agent_config.json").read_text(encoding="utf-8"))
    assert isinstance(cfg, dict)
