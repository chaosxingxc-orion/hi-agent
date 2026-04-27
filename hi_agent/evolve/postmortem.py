"""Deprecated: use hi_agent.evolve.retrospective instead."""

import warnings

warnings.warn(
    "hi_agent.evolve.postmortem is deprecated; use hi_agent.evolve.retrospective instead. "
    "Removed in Wave 14.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.evolve.retrospective import *  # noqa: F403
from hi_agent.evolve.retrospective import (  # noqa: F401
    PostmortemAnalyzer,
    _build_retrospective_prompt,
    _infer_scope,
    _parse_llm_changes,
)
