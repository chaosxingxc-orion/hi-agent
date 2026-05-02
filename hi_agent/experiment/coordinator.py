"""Deprecated: use hi_agent.operations.coordinator instead."""
import warnings

warnings.warn(
    "hi_agent.experiment.coordinator is deprecated; use hi_agent.operations.coordinator instead.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.operations.coordinator import *  # noqa: F403  expiry_wave: Wave 29
