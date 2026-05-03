"""DEPRECATED — use ``hi_agent.profiles`` instead. Removed in W34.

This shim was added when ``hi_agent.profile.manager`` was merged into
``hi_agent.profiles.directory``; ``profiles`` is the canonical package.
"""

import warnings

warnings.warn(
    "hi_agent.profile is deprecated; use hi_agent.profiles",
    DeprecationWarning,
    stacklevel=2,
)

from hi_agent.profiles.directory import (  # expiry_wave: Wave 34
    GLOBAL_PROFILE_ID,
    ProfileDirectoryManager,
)

__all__ = ["GLOBAL_PROFILE_ID", "ProfileDirectoryManager"]
