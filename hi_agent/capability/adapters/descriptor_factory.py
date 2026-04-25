"""Capability descriptor factory: auto-generates metadata via naming heuristics.

CO-6: The duplicate CapabilityDescriptor class that used to live here has been
removed.  The single canonical definition is now
hi_agent.capability.registry.CapabilityDescriptor.

This module re-exports CapabilityDescriptor for backward compatibility so that
all existing import sites (tests, adapters) continue to work without change.

Use build_capability_view(desc) to get the dict shape consumed by the adapter
layer when you need to expose a descriptor over a generic interface.
"""

from __future__ import annotations

from typing import ClassVar

# Re-export canonical class — single import point going forward.
from hi_agent.capability.registry import CapabilityDescriptor

__all__ = [
    "CapabilityDescriptor",
    "CapabilityDescriptorFactory",
    "build_capability_view",
]


def build_capability_view(desc: CapabilityDescriptor) -> dict:
    """Produce the dict shape needed by the adapter/toolset layer.

    Maps canonical CapabilityDescriptor fields to the keys expected by the
    CoreToolAdapter and related consumers.  Unknown fields are silently
    omitted — only the listed keys are guaranteed.

    Args:
        desc: A canonical CapabilityDescriptor instance.

    Returns:
        Dict with keys: name, effect_class, tags, sandbox_level, description,
        parameters, extra, toolset_id, required_env, output_budget_tokens,
        availability_probe, risk_class, requires_approval, requires_auth,
        source_reference_policy, provenance_required.
    """
    return {
        "name": desc.name,
        "effect_class": desc.effect_class,
        "tags": list(desc.tags),
        "sandbox_level": desc.sandbox_level,
        "description": desc.description,
        "parameters": dict(desc.parameters),
        "extra": dict(desc.extra),
        "toolset_id": desc.toolset_id,
        "required_env": dict(desc.required_env),
        "output_budget_tokens": desc.output_budget_tokens,
        "availability_probe": desc.availability_probe,
        # Governance fields (platform layer)
        "risk_class": desc.risk_class,
        "requires_approval": desc.requires_approval,
        "requires_auth": desc.requires_auth,
        "source_reference_policy": desc.source_reference_policy,
        "provenance_required": desc.provenance_required,
    }


class CapabilityDescriptorFactory:
    """Auto-generates CapabilityDescriptor metadata using naming heuristics."""

    # Effect class heuristics based on tool name prefixes / leading verbs.
    EFFECT_HEURISTICS: ClassVar[dict[str, str]] = {
        "read": "read_only",
        "search": "read_only",
        "query": "read_only",
        "get": "read_only",
        "list": "read_only",
        "fetch": "read_only",
        "find": "read_only",
        "lookup": "read_only",
        "write": "idempotent_write",
        "create": "idempotent_write",
        "update": "idempotent_write",
        "set": "idempotent_write",
        "put": "idempotent_write",
        "upsert": "idempotent_write",
        "delete": "irreversible_write",
        "send": "irreversible_write",
        "remove": "irreversible_write",
        "drop": "irreversible_write",
        "purge": "irreversible_write",
    }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def infer_effect_class(self, tool_name: str) -> str:
        """Infer effect_class from tool name using verb heuristics.

        The first matching verb at the start of *tool_name* (split on ``_``)
        determines the class.  Falls back to ``"unknown_effect"``.
        """
        parts = tool_name.lower().replace("-", "_").split("_")
        for part in parts:
            if part in self.EFFECT_HEURISTICS:
                return self.EFFECT_HEURISTICS[part]
        return "unknown_effect"

    def build_descriptor(
        self,
        tool_info: dict | str,
        overrides: dict | None = None,
    ) -> CapabilityDescriptor:
        """Build a full descriptor with auto-inferred + manual override fields.

        Args:
            tool_info: Dict with at least ``name``; optionally ``description``,
                ``parameters``, ``effect_class``, ``tags``.  May also be a
                plain string, in which case it is treated as the capability name.
            overrides: Optional dict whose keys shadow any inferred or
                tool_info-supplied values.  Useful for per-tool YAML config.

        Returns:
            A frozen ``CapabilityDescriptor`` instance.
        """
        if isinstance(tool_info, str):
            tool_info = {"name": tool_info}
        name: str = tool_info["name"]
        overrides = overrides or {}

        effect_class = overrides.get(
            "effect_class",
            tool_info.get("effect_class", self.infer_effect_class(name)),
        )

        raw_tags = overrides.get("tags", tool_info.get("tags", ()))
        tags = tuple(raw_tags) if not isinstance(raw_tags, tuple) else raw_tags

        sandbox_level = overrides.get(
            "sandbox_level",
            tool_info.get("sandbox_level", "none"),
        )

        description = overrides.get(
            "description",
            tool_info.get("description", ""),
        )

        parameters = overrides.get(
            "parameters",
            tool_info.get("parameters", {}),
        )

        extra = overrides.get("extra", tool_info.get("extra", {}))

        # Infer required_env for known LLM-backed capabilities (W4-001)
        name_lower = name.lower()
        if any(kw in name_lower for kw in ("llm", "plan", "reflect", "reason", "generate", "chat")):
            inferred_required_env: dict = {"ANTHROPIC_API_KEY": "LLM API key (or OPENAI_API_KEY)"}
        else:
            inferred_required_env = {}
        required_env = overrides.get(
            "required_env", tool_info.get("required_env", inferred_required_env)
        )

        toolset_id = overrides.get("toolset_id", tool_info.get("toolset_id", "default"))
        output_budget_tokens = overrides.get(
            "output_budget_tokens", tool_info.get("output_budget_tokens", 0)
        )
        availability_probe = overrides.get(
            "availability_probe", tool_info.get("availability_probe")
        )

        return CapabilityDescriptor(
            name=name,
            effect_class=effect_class,
            tags=tags,
            sandbox_level=sandbox_level,
            description=description,
            parameters=parameters,
            extra=extra,
            toolset_id=toolset_id,
            required_env=required_env,
            output_budget_tokens=output_budget_tokens,
            availability_probe=availability_probe,
        )
