"""DEPRECATED — use ``hi_agent.profiles.directory`` instead. Removed in W34.

This shim re-exports ``ProfileDirectoryManager`` and ``GLOBAL_PROFILE_ID``
from their new home in :mod:`hi_agent.profiles.directory` so callers using
``from hi_agent.profile.manager import ...`` keep working until W34.
"""

from hi_agent.profiles.directory import (  # noqa: F401  # expiry_wave: Wave 34
    GLOBAL_PROFILE_ID,
    ProfileDirectoryManager,
)

__all__ = ["GLOBAL_PROFILE_ID", "ProfileDirectoryManager"]
