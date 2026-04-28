"""Artifact storage path utilities including path traversal protection (J2).

All artifact file-write operations must pass target paths through
``assert_within_workspace()`` before opening the file, to prevent directory
traversal attacks where a crafted artifact path (e.g. ``../../etc/passwd``)
could escape the intended workspace root.

Usage::

    from hi_agent.artifacts.storage import assert_within_workspace
    assert_within_workspace(path, workspace_root)
    with open(path, "w") as f:
        ...
"""

from __future__ import annotations

import os
from pathlib import Path


def _default_workspace_root() -> Path:
    """Return the effective workspace root from the environment.

    Uses ``HI_AGENT_DATA_DIR`` when set, otherwise falls back to the current
    working directory.  Resolved to an absolute path.
    """
    data_dir = os.environ.get("HI_AGENT_DATA_DIR", "").strip()
    return Path(data_dir).resolve() if data_dir else Path(".").resolve()


def assert_within_workspace(
    path: str | Path,
    workspace_root: str | Path | None = None,
) -> Path:
    """Verify that *path* does not escape *workspace_root*.

    Resolves both paths to their absolute, symlink-free forms and checks that
    the resolved path starts with the resolved workspace root.

    Args:
        path: The artifact path to validate.
        workspace_root: The workspace root to enforce.  When ``None``, uses
            ``HI_AGENT_DATA_DIR`` (or the current directory as fallback).

    Returns:
        The resolved ``Path`` object for the validated path.

    Raises:
        ValueError: If *path* resolves to a location outside *workspace_root*.
    """
    root = (
        Path(workspace_root).resolve()
        if workspace_root is not None
        else _default_workspace_root()
    )
    resolved = Path(path).resolve()
    # Use str prefix check; ensure root ends with sep to avoid prefix collision
    # between e.g. /data/runs and /data/runs-extra.
    root_str = str(root)
    resolved_str = str(resolved)
    if not (resolved_str == root_str or resolved_str.startswith(root_str + os.sep)):
        raise ValueError(
            f"Artifact path {path!r} escapes workspace root {root!r} "
            f"(resolved: {resolved!r})"
        )
    return resolved
