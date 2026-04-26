"""Deprecated: use hi_agent.operations.op_store instead."""
import warnings

warnings.warn(
    "hi_agent.experiment.op_store is deprecated; use hi_agent.operations.op_store instead.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.operations.op_store import *  # noqa: F403
