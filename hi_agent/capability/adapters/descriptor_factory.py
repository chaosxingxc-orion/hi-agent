"""Auto-generates CapabilityDescriptor metadata using naming heuristics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass(frozen=True)
class CapabilityDescriptor:
    """Rich metadata describing a capability beyond its callable spec.

    Fields:
        name: Canonical capability name.
        effect_class: One of read_only, idempotent_write, irreversible_write,
            unknown_effect.
        tags: Free-form classification tags.
        sandbox_level: Isolation tier (e.g. "none", "container", "vm").
        description: Human-readable summary.
        parameters: JSON-schema dict of accepted parameters.
        extra: Catch-all for additional metadata.
    """

    name: str
    effect_class: str = "unknown_effect"
    tags: tuple[str, ...] = ()
    sandbox_level: str = "none"
    description: str = ""
    parameters: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    # Governance metadata (W4-001)
    toolset_id: str = "default"
    required_env: dict = field(default_factory=dict)   # {"ENV_VAR": "description"}
    output_budget_tokens: int = 0                       # 0 = unlimited
    availability_probe: object = field(default=None)   # Callable[[], tuple[bool, str]] | None


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
        tool_info: "dict | str",
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
        required_env = overrides.get("required_env", tool_info.get("required_env", inferred_required_env))

        toolset_id = overrides.get("toolset_id", tool_info.get("toolset_id", "default"))
        output_budget_tokens = overrides.get(
            "output_budget_tokens", tool_info.get("output_budget_tokens", 0)
        )
        availability_probe = overrides.get(
            "availability_probe", tool_info.get("availability_probe", None)
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
