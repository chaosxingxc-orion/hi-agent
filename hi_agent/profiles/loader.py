"""Load ProfileSpec instances from JSON files in a directory.

JSON profile file format::

    {
        "profile_id": "my_research",
        "display_name": "My Research Profile",
        "description": "Optional human-readable description.",
        "stage_actions": {"S1_plan": "search", "S3_synthesize": "synthesize"},
        "required_capabilities": ["web_search", "document_reader"],
        "config_overrides": {},
        "metadata": {}
    }

All fields except ``profile_id`` and ``display_name`` are optional.
Callable fields (``stage_graph_factory``, ``evaluator_factory``) cannot be
expressed in JSON and are always ``None`` after a JSON load.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.profiles.registry import ProfileRegistry

logger = logging.getLogger(__name__)


def load_profiles_from_dir(profile_dir: Path, registry: ProfileRegistry) -> list[str]:
    """Load JSON profile files from *profile_dir* and register them.

    Each ``*.json`` file in the directory is parsed as a :class:`ProfileSpec`
    via :meth:`ProfileSpec.from_dict`.  Files that fail to parse are logged at
    WARNING and skipped — they do not block other profiles from loading.

    Already-registered profile IDs are skipped without error so that callers
    can call this function more than once without raising ``ValueError``.

    Args:
        profile_dir: Directory containing JSON profile files.  Must exist.
        registry: Target :class:`ProfileRegistry` to register profiles into.

    Returns:
        List of profile IDs that were successfully registered in this call.

    Raises:
        ValueError: If *profile_dir* exists but is not a directory.
    """
    from hi_agent.profiles.contracts import ProfileSpec

    dir_path = Path(profile_dir)
    if not dir_path.exists():
        logger.debug("load_profiles_from_dir: %s does not exist; skipping.", dir_path)
        return []
    if not dir_path.is_dir():
        raise ValueError(f"profile_dir must be a directory, got: {dir_path}")

    registered: list[str] = []
    for json_file in sorted(dir_path.glob("*.json")):
        try:
            raw = json_file.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "load_profiles_from_dir: skipping %s — cannot parse: %s",
                json_file.name,
                exc,
            )
            continue

        if not isinstance(data, dict):
            logger.warning(
                "load_profiles_from_dir: skipping %s — root must be a JSON object.",
                json_file.name,
            )
            continue

        try:
            spec = ProfileSpec.from_dict(data)
        except (KeyError, TypeError) as exc:
            logger.warning(
                "load_profiles_from_dir: skipping %s — invalid profile data: %s",
                json_file.name,
                exc,
            )
            continue

        if registry.has(spec.profile_id):
            logger.debug(
                "load_profiles_from_dir: profile %r already registered; skipping %s.",
                spec.profile_id,
                json_file.name,
            )
            continue

        try:
            registry.register(spec)
            registered.append(spec.profile_id)
            logger.info(
                "load_profiles_from_dir: registered profile %r from %s.",
                spec.profile_id,
                json_file.name,
            )
        except ValueError as exc:
            logger.warning(
                "load_profiles_from_dir: could not register profile %r from %s: %s",
                spec.profile_id,
                json_file.name,
                exc,
            )

    return registered
