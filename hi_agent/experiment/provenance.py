"""Deprecated: use hi_agent.operations.provenance instead."""
import warnings

warnings.warn(
    "hi_agent.experiment.provenance is deprecated; use hi_agent.operations.provenance instead.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.operations.provenance import *  # noqa: F403  expiry_wave: Wave 28
