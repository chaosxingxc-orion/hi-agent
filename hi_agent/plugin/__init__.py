"""Deprecated: use hi_agent.plugins instead.

This package is a compatibility shim for Wave 11 migration.
Retained for backward compatibility; new code must import from
``hi_agent.plugins``.
"""
import warnings

warnings.warn(
    "hi_agent.plugin is deprecated; use hi_agent.plugins instead. "
    "This shim is retained for backward compatibility only.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.plugins import *  # noqa: F403  expiry_wave: permanent
from hi_agent.plugins import (
    __all__,  # noqa: F401  expiry_wave: permanent  # scope: legacy-compatibility — re-export shim for backward compat
)
