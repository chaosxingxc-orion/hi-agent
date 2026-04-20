"""Runtime profile registry for business agent configuration injection."""

from hi_agent.profiles.contracts import ProfileSpec
from hi_agent.profiles.registry import ProfileRegistry

__all__ = ["ProfileRegistry", "ProfileSpec"]
