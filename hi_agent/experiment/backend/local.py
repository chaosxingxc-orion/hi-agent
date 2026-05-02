"""Deprecated: use hi_agent.operations.backend.local instead."""
import warnings

warnings.warn(
    "hi_agent.experiment.backend.local is deprecated; "
    "use hi_agent.operations.backend.local instead.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.operations.backend.local import *  # noqa: F403  expiry_wave: permanent
