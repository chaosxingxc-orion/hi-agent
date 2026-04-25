"""hi-agent init subcommand — scaffold a posture-specific config directory.

Usage:
    hi-agent init --posture research --config-dir ./my_config

Creates:
    <config-dir>/hi_agent_config.json   — runtime tunables
    <config-dir>/profiles/<posture>.json -- minimal valid profile
    <config-dir>/.env.example            — documented env vars
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Locate the templates directory relative to this file.
_TEMPLATES_ROOT = Path(__file__).parent.parent / "templates" / "posture"

_VALID_POSTURES = ("dev", "research", "prod")


def run_init(args) -> None:
    """Scaffold a posture-specific config directory.

    Args:
        args: Parsed CLI arguments with ``posture`` and ``config_dir`` fields.
    """
    posture: str = args.posture
    config_dir = Path(args.config_dir).resolve()

    if posture not in _VALID_POSTURES:
        print(
            f"error: --posture must be one of {_VALID_POSTURES}, got {posture!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    template_dir = _TEMPLATES_ROOT / posture
    if not template_dir.exists():
        print(
            f"error: template directory not found: {template_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Create destination directory tree
    profiles_dir = config_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    # Copy / render each template file
    _scaffold_file(
        template_dir / "hi_agent_config.json.tmpl",
        config_dir / "hi_agent_config.json",
    )
    _scaffold_file(
        template_dir / "profiles" / f"{posture}.json.tmpl",
        profiles_dir / f"{posture}.json",
    )
    _scaffold_file(
        template_dir / ".env.example.tmpl",
        config_dir / ".env.example",
    )

    print(f"Scaffolded {posture} config at {config_dir}")


def _scaffold_file(src: Path, dst: Path) -> None:
    """Copy *src* template to *dst*, skipping if *dst* already exists.

    Prints a line for each file written.
    """
    if dst.exists():
        print(f"  skip (exists): {dst}")
        return
    if not src.exists():
        logger.warning("init: template file not found, skipping: %s", src)
        return
    shutil.copy2(src, dst)
    print(f"  write: {dst}")


def _validate_json_files(config_dir: Path, posture: str) -> bool:
    """Return True if the written JSON files parse correctly.

    Called by tests to verify scaffolded output is valid JSON.
    """
    paths = [
        config_dir / "hi_agent_config.json",
        config_dir / "profiles" / f"{posture}.json",
    ]
    for path in paths:
        if not path.exists():
            return False
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
    return True
