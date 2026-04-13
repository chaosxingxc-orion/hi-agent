"""Profile contract: business agent runtime configuration injected into the platform.

A ProfileSpec defines what capabilities, stage routing, evaluator, and
config overrides a business agent needs from the hi-agent platform.
The platform is agnostic to which profile is active — it simply reads
the profile's declared bindings at runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProfileSpec:
    """Declarative runtime configuration for a business agent profile.

    Business agents register a ProfileSpec to inject:
    - which capabilities are required
    - how stages map to action_kinds (overrides RuleRouteEngine defaults)
    - an optional custom stage graph topology
    - an optional custom evaluator
    - any TraceConfig overrides
    """

    profile_id: str
    display_name: str
    description: str = ""
    required_capabilities: list[str] = field(default_factory=list)
    stage_actions: dict[str, str] = field(default_factory=dict)
    # Callables are excluded from serialization; restored as None on from_dict.
    stage_graph_factory: Callable[[], Any] | None = field(default=None, repr=False)
    evaluator_factory: Callable[..., Any] | None = field(default=None, repr=False)
    config_overrides: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (callable fields omitted)."""
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "description": self.description,
            "required_capabilities": list(self.required_capabilities),
            "stage_actions": dict(self.stage_actions),
            "config_overrides": dict(self.config_overrides),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileSpec:
        """Deserialize from a plain dict (callable fields default to None)."""
        return cls(
            profile_id=data["profile_id"],
            display_name=data["display_name"],
            description=data.get("description", ""),
            required_capabilities=list(data.get("required_capabilities", [])),
            stage_actions=dict(data.get("stage_actions", {})),
            config_overrides=dict(data.get("config_overrides", {})),
            metadata=dict(data.get("metadata", {})),
        )
