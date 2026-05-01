"""Deprecated: use hi_agent.operations.backend instead."""
import warnings

warnings.warn(
    "hi_agent.experiment.backend is deprecated; use hi_agent.operations.backend instead.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.operations.backend import *  # noqa: F403  expiry_wave: Wave 28
