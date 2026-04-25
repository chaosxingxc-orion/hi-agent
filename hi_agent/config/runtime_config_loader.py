"""Load hi_agent_config.json for runtime tunables.

Exposes ``load_runtime_config`` which reads a JSON file and returns a plain
dict covering three top-level keys:

- ``run_manager``   — ``max_concurrent``, ``queue_size``
- ``idempotency``   — ``ttl_seconds``
- ``rate_limit``    — ``max_per_minute``

The file is optional: a missing file returns an empty dict without error.

Resolution order:
1. Explicit ``path`` argument.
2. ``HI_AGENT_CONFIG_DIR/hi_agent_config.json`` (env var or default config/).
3. Returns ``{}`` if not found.

Also exposes ``get_posture`` — the current :class:`~hi_agent.config.posture.Posture`
derived from the ``HI_AGENT_POSTURE`` environment variable.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from hi_agent.config.posture import Posture

logger = logging.getLogger(__name__)


def get_posture() -> Posture:
    """Return the current execution posture from HI_AGENT_POSTURE (default: dev)."""
    return Posture.from_env()


def load_runtime_config(path: Path | None = None) -> dict:
    """Load hi_agent_config.json from *path* or the resolved config directory.

    Returns an empty dict if the file is not found.

    Args:
        path: Explicit path to the JSON file.  When ``None``, the file is
            looked up as ``hi_agent_config.json`` inside the directory resolved
            by ``HI_AGENT_CONFIG_DIR`` (or the repo-root ``config/`` directory
            as back-compat fallback).

    Returns:
        Parsed JSON dict, or ``{}`` if the file does not exist.

    Raises:
        ValueError: If the file exists but is not valid JSON.
    """
    resolved = _resolve_path(path)
    if resolved is None or not resolved.exists():
        return {}

    try:
        raw = resolved.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"hi_agent_config.json is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("hi_agent_config.json: root must be a JSON object")

    logger.info("load_runtime_config: loaded from %s", resolved)
    return data


def _resolve_path(path: Path | None) -> Path | None:
    """Return the resolved path to hi_agent_config.json, or None if unset."""
    if path is not None:
        return path
    env = os.environ.get("HI_AGENT_CONFIG_DIR")
    base = Path(env) if env else Path(__file__).parent.parent.parent / "config"
    return base / "hi_agent_config.json"
