"""Skill definition with SKILL.md-compatible format.

Skills are Markdown files with YAML-style frontmatter, matching the
claude-code and OpenClaw convention::

# ---------------------------------------------------------------------------
# Execution Strategy & Restart Policy — downstream reference
# ---------------------------------------------------------------------------
# Execution strategy is NOT a SkillDefinition or RunExecutor constructor
# field.  It is selected by the caller choosing which RunExecutor method to
# invoke:
#
#   - Sequential stage traversal  →  RunExecutor.execute()
#   - Dynamic graph (backtrack + multi-successor)  →  RunExecutor.execute_graph()
#   - Full asyncio with AsyncTaskScheduler + KernelFacade  →  RunExecutor.execute_async()
#
# Restart policy ("reflect(N)", "retry(N)", "retry+escalate") is configured
# by passing a RestartPolicyEngine instance to the RunExecutor constructor
# keyword argument `restart_policy_engine: RestartPolicyEngine | None`.
# The RestartPolicyEngine reads policy from TaskContract fields and from the
# PolicyVersionSet passed to the constructor.
# ---------------------------------------------------------------------------

    ---
    name: analyze-data
    version: 1.0.0
    description: Analyze structured datasets
    when_to_use: When user needs data analysis
    allowed_tools: [Bash, Read, Write]
    model: default
    tags: [analysis, data]
    requires:
      bins: [python3]
      env: [DATA_DIR]
    lifecycle_stage: certified
    confidence: 0.85
    cost_estimate_tokens: 500
    ---

    # Analyze Data

    (Skill prompt content that gets injected into LLM context)
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Lightweight YAML-subset parser (no external deps)
# ---------------------------------------------------------------------------


def _parse_yaml_value(raw: str) -> str | int | float | bool | list[str]:
    """Parse a single YAML value (string, int, float, bool, or list)."""
    val = raw.strip()
    if not val:
        return ""

    # Boolean
    if val.lower() in ("true", "yes"):
        return True
    if val.lower() in ("false", "no"):
        return False

    # Inline list: [a, b, c]
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1]
        if not inner.strip():
            return []
        items: list[str] = []
        for item in inner.split(","):
            item = item.strip().strip("\"'")
            if item:
                items.append(item)
        return items

    # Numeric
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:  # rule7-exempt: expiry_wave="Wave 29" replacement_test: wave22-tests
        pass

    # Plain string - strip quotes
    return val.strip("\"'")


def _parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Split frontmatter from body, return (metadata_dict, body).

    Supports nested ``requires:`` block with ``bins:`` and ``env:`` keys.
    """
    pattern = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)
    m = pattern.match(text)
    if not m:
        return {}, text

    raw_fm = m.group(1)
    body = m.group(2)

    meta: dict[str, object] = {}
    current_block: str | None = None

    for line in raw_fm.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Detect nested block start (e.g. "requires:")
        if stripped.endswith(":") and ":" not in stripped[:-1]:
            current_block = stripped[:-1]
            continue

        # Indented line inside a block
        if line.startswith("  ") and current_block is not None:
            key_val = stripped.split(":", 1)
            if len(key_val) == 2:
                sub_key = f"{current_block}_{key_val[0].strip()}"
                meta[sub_key] = _parse_yaml_value(key_val[1])
            continue

        # Top-level key
        current_block = None
        key_val = stripped.split(":", 1)
        if len(key_val) == 2:
            meta[key_val[0].strip()] = _parse_yaml_value(key_val[1])

    return meta, body


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

_CHARS_PER_TOKEN = 4  # rough approximation


def _estimate_tokens(text: str) -> int:
    """Rough token count (chars / 4)."""
    return max(1, len(text) // _CHARS_PER_TOKEN) if text else 0


# ---------------------------------------------------------------------------
# SkillDefinition
# ---------------------------------------------------------------------------


@dataclass
class SkillDefinition:
    """A skill loaded from SKILL.md or created programmatically.

    Wave 24 H1: tenant_id is part of the spine — research/prod construction
    requires a non-empty tenant_id so per-tenant skill registries can be
    partitioned downstream (see allowlists.yaml W24-deferred entries
    handle_skills_evolve / handle_skill_optimize / handle_skill_promote).
    """

    skill_id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    when_to_use: str = ""
    prompt_content: str = ""  # The actual prompt text
    allowed_tools: list[str] = field(default_factory=list)
    model: str = "default"
    tags: list[str] = field(default_factory=list)
    lifecycle_stage: str = "candidate"
    confidence: float = 0.5
    cost_estimate_tokens: int = 0
    # Eligibility requirements (OpenClaw pattern)
    requires_bins: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)
    # Metadata
    source: str = "file"  # file, generated, evolved, imported
    source_path: str = ""
    created_at: str = ""
    updated_at: str = ""
    tenant_id: str = ""  # scope: spine-required — enforced under strict posture

    def __post_init__(self) -> None:
        from hi_agent.config.posture import Posture

        if Posture.from_env().is_strict and not self.tenant_id:
            raise ValueError(
                "SkillDefinition.tenant_id required under research/prod posture"
            )

    # ------------------------------------------------------------------
    # Downstream-compatible aliases (additive, do not rename source fields)
    # ------------------------------------------------------------------

    @property
    def system_prompt_fragment(self) -> str:
        """Alias for ``prompt_content`` (downstream API compatibility)."""
        return self.prompt_content

    @property
    def tool_specs(self) -> list[str]:
        """Alias for ``allowed_tools`` (downstream API compatibility)."""
        return self.allowed_tools

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_full_prompt(self) -> str:
        """Full prompt for injection (inline mode)."""
        parts: list[str] = []
        parts.append(f"## Skill: {self.name}")
        if self.description:
            parts.append(f"Description: {self.description}")
        if self.when_to_use:
            parts.append(f"When to use: {self.when_to_use}")
        if self.allowed_tools:
            parts.append(f"Allowed tools: {', '.join(self.allowed_tools)}")
        if self.tags:
            parts.append(f"Tags: {', '.join(self.tags)}")
        parts.append("")
        parts.append(self.prompt_content)
        return "\n".join(parts)

    def to_compact_entry(self) -> str:
        """Compact entry: name + path only (OpenClaw pattern, saves tokens)."""
        if self.source_path:
            return f"- {self.name}: {self.source_path}"
        return f"- {self.name}"

    def to_frontmatter_md(self) -> str:
        """Serialize back to SKILL.md format with frontmatter."""
        lines: list[str] = ["---"]
        lines.append(f"name: {self.name}")
        lines.append(f"version: {self.version}")
        if self.description:
            lines.append(f"description: {self.description}")
        if self.when_to_use:
            lines.append(f"when_to_use: {self.when_to_use}")
        if self.allowed_tools:
            tools_str = ", ".join(self.allowed_tools)
            lines.append(f"allowed_tools: [{tools_str}]")
        lines.append(f"model: {self.model}")
        if self.tags:
            tags_str = ", ".join(self.tags)
            lines.append(f"tags: [{tags_str}]")
        if self.requires_bins or self.requires_env:
            lines.append("requires:")
            if self.requires_bins:
                bins_str = ", ".join(self.requires_bins)
                lines.append(f"  bins: [{bins_str}]")
            if self.requires_env:
                env_str = ", ".join(self.requires_env)
                lines.append(f"  env: [{env_str}]")
        lines.append(f"lifecycle_stage: {self.lifecycle_stage}")
        lines.append(f"confidence: {self.confidence}")
        if self.cost_estimate_tokens:
            lines.append(f"cost_estimate_tokens: {self.cost_estimate_tokens}")
        lines.append("---")
        lines.append("")
        lines.append(self.prompt_content)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_markdown(cls, content: str, source_path: str = "") -> SkillDefinition:
        """Parse a SKILL.md file (frontmatter + content)."""
        meta, body = _parse_frontmatter(content)

        name = str(meta.get("name", ""))
        # Derive skill_id from name or filename
        if name:
            skill_id = name.lower().replace(" ", "-")
        elif source_path:
            skill_id = os.path.splitext(os.path.basename(source_path))[0].lower()
        else:
            skill_id = "unknown"

        def _str(key: str) -> str:
            v = meta.get(key, "")
            return str(v) if v else ""

        def _list(key: str) -> list[str]:
            v = meta.get(key, [])
            if isinstance(v, list):
                return v
            if isinstance(v, str) and v:
                return [v]
            return []

        def _float(key: str, default: float) -> float:
            v = meta.get(key, default)
            try:
                return float(v)  # type: ignore[arg-type]  expiry_wave: Wave 29
            except (ValueError, TypeError):
                return default

        def _int(key: str, default: int) -> int:
            v = meta.get(key, default)
            try:
                return int(v)  # type: ignore[arg-type]  expiry_wave: Wave 29
            except (ValueError, TypeError):
                return default

        now = datetime.now(UTC).isoformat()

        return cls(
            skill_id=skill_id,
            name=name,
            version=_str("version") or "0.1.0",
            description=_str("description"),
            when_to_use=_str("when_to_use"),
            prompt_content=body.strip(),
            allowed_tools=_list("allowed_tools"),
            model=_str("model") or "default",
            tags=_list("tags"),
            lifecycle_stage=_str("lifecycle_stage") or "candidate",
            confidence=_float("confidence", 0.5),
            cost_estimate_tokens=_int("cost_estimate_tokens", 0),
            requires_bins=_list("requires_bins"),
            requires_env=_list("requires_env"),
            source="file",
            source_path=source_path,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------

    def check_eligibility(self) -> tuple[bool, str]:
        """Check if skill can run (bins exist, env vars set).

        Returns:
            A ``(eligible, reason)`` tuple.
        """
        missing_bins: list[str] = []
        for b in self.requires_bins:
            if shutil.which(b) is None:
                missing_bins.append(b)

        missing_env: list[str] = []
        for e in self.requires_env:
            if not os.environ.get(e):
                missing_env.append(e)

        if missing_bins or missing_env:
            parts: list[str] = []
            if missing_bins:
                parts.append(f"missing binaries: {', '.join(missing_bins)}")
            if missing_env:
                parts.append(f"missing env vars: {', '.join(missing_env)}")
            return False, "; ".join(parts)

        return True, ""

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    def estimate_tokens(self) -> int:
        """Estimate token cost of full prompt."""
        if self.cost_estimate_tokens > 0:
            return self.cost_estimate_tokens
        return _estimate_tokens(self.to_full_prompt())
