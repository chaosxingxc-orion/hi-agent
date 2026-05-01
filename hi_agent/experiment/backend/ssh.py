"""Deprecated: use hi_agent.operations.backend.ssh instead."""
import warnings

warnings.warn(
    "hi_agent.experiment.backend.ssh is deprecated; use hi_agent.operations.backend.ssh instead.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.operations.backend.ssh import *  # noqa: F403  expiry_wave: Wave 28
