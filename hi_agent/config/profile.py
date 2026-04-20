# hi_agent/config/profile.py
"""Profile-aware deep merge utilities for ConfigStack."""

from __future__ import annotations

import json
import os


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*.

    Scalar values in *override* replace those in *base*.
    Dict values are merged recursively.
    *base* is never mutated.
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def profile_path_for(base_path: str | None, profile: str) -> str | None:
    """Return the path for ``config.<profile>.json`` next to *base_path*.

    Returns ``None`` if *base_path* is ``None``.
    """
    if base_path is None:
        return None
    directory = os.path.dirname(os.path.abspath(base_path))
    return os.path.join(directory, f"config.{profile}.json")


def load_profile_file(base_path: str | None, profile: str) -> dict:
    """Load the profile override file and return its contents as a dict.

    Returns an empty dict if the file does not exist or base_path is None.
    """
    path = profile_path_for(base_path, profile)
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
