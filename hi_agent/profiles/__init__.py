"""Runtime profile registry for business agent configuration injection.

Includes profile-directory primitives (``ProfileDirectoryManager``,
``GLOBAL_PROFILE_ID``) merged here from the deprecated ``hi_agent.profile``
package; the legacy import path still works via a deprecation shim and will
be removed in Wave 34.
"""

from hi_agent.profiles.contracts import ProfileSpec
from hi_agent.profiles.directory import GLOBAL_PROFILE_ID, ProfileDirectoryManager
from hi_agent.profiles.registry import ProfileRegistry
from hi_agent.profiles.rule15_volces import (
    RULE15_PROBE_CAPABILITY,
    RULE15_PROBE_STAGE,
    build_rule15_volces_profile,
    register_rule15_probe_capability,
)

__all__ = [
    "GLOBAL_PROFILE_ID",
    "RULE15_PROBE_CAPABILITY",
    "RULE15_PROBE_STAGE",
    "ProfileDirectoryManager",
    "ProfileRegistry",
    "ProfileSpec",
    "build_rule15_volces_profile",
    "register_rule15_probe_capability",
]
