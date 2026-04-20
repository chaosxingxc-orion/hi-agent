"""Path traversal prevention policy (P0-1c).

Provides safe_resolve() to validate user-supplied paths against a base directory.
"""

from __future__ import annotations

import sys
from pathlib import Path


class PathPolicyViolation(Exception):
    """Raised when a path fails security policy."""


def safe_resolve(base_dir: Path | str, user_path: str, *, allow_absolute: bool = False) -> Path:
    """Resolve user_path relative to base_dir.

    Raises PathPolicyViolation if the resolved path escapes base_dir.

    Rules:
    1. Reject null bytes in the path.
    2. Reject absolute paths (unless allow_absolute=True).
    3. On Windows: reject drive-letter paths (C:\\...), UNC paths (\\\\server\\share).
    4. Join base_dir / user_path and resolve (follow symlinks via Path.resolve()).
    5. Verify the resolved path starts with resolved base_dir.
    """
    if "\x00" in user_path:
        raise PathPolicyViolation("Null byte detected in path")

    # Windows-specific checks: UNC paths and drive-letter paths
    if (
        sys.platform == "win32"
        or user_path.startswith("\\\\")
        or (len(user_path) >= 2 and user_path[1] == ":")
    ):
        if user_path.startswith("\\\\"):
            raise PathPolicyViolation(f"UNC path not allowed: {user_path!r}")
        if len(user_path) >= 2 and user_path[1] == ":":
            raise PathPolicyViolation(f"Drive-letter path not allowed: {user_path!r}")

    # Check for absolute paths
    if not allow_absolute and Path(user_path).is_absolute():
        raise PathPolicyViolation(f"Absolute path not allowed: {user_path!r}")

    base = Path(base_dir).resolve()
    candidate = (base / user_path).resolve()

    # Verify candidate is within base_dir
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise PathPolicyViolation(
            f"Path {user_path!r} resolves outside base directory {str(base)!r}"
        ) from exc

    return candidate
