"""Runtime profile registry for business agent configuration injection."""

from hi_agent.profiles.contracts import ProfileSpec
from hi_agent.profiles.registry import ProfileRegistry
from hi_agent.profiles.rule15_volces import (
    RULE15_PROBE_CAPABILITY,
    RULE15_PROBE_STAGE,
    build_rule15_volces_profile,
    register_rule15_probe_capability,
)

__all__ = [
    "RULE15_PROBE_CAPABILITY",
    "RULE15_PROBE_STAGE",
    "ProfileRegistry",
    "ProfileSpec",
    "build_rule15_volces_profile",
    "register_rule15_probe_capability",
]
