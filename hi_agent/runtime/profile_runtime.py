"""Profile runtime resolver — turns a profile_id into live runtime objects.

This module is the single place where a ``ProfileSpec`` is converted into
the concrete instances that the executor path needs:

- ``stage_graph`` — the StageGraph topology to execute
- ``stage_actions`` — the {stage_id: capability_name} mapping for routing
- ``evaluator`` — the Evaluator instance for quality assessment
- ``config_overrides`` — per-run TraceConfig patches from the profile
- ``required_capabilities`` — capability names the profile declares needed

The resolver separates concerns: the ``SystemBuilder`` asks for a
``ResolvedProfile`` by ID; callers outside the builder never interact with
the raw ``ProfileSpec`` at runtime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ResolvedProfile:
    """Resolved runtime objects derived from a ProfileSpec.

    All fields are optional — ``None`` means "use platform default".
    """

    profile_id: str
    stage_graph: Any | None = None          # StageGraph instance
    stage_actions: dict[str, str] = field(default_factory=dict)
    evaluator: Any | None = None            # hi_agent.evaluation.contracts.Evaluator
    config_overrides: dict[str, Any] = field(default_factory=dict)
    required_capabilities: list[str] = field(default_factory=list)

    @property
    def has_custom_graph(self) -> bool:
        return self.stage_graph is not None

    @property
    def has_custom_actions(self) -> bool:
        return bool(self.stage_actions)

    @property
    def has_evaluator(self) -> bool:
        return self.evaluator is not None


class ProfileRuntimeResolver:
    """Resolve a profile_id to a ResolvedProfile using a ProfileRegistry.

    Usage::

        resolver = ProfileRuntimeResolver(registry)
        resolved = resolver.resolve("rnd_agent")
        # resolved.stage_graph, resolved.evaluator, etc. are ready to inject.
    """

    def __init__(self, registry: Any) -> None:
        """Args:
        registry: ``hi_agent.profiles.registry.ProfileRegistry`` instance.
        """
        self._registry = registry

    def resolve(self, profile_id: str | None) -> ResolvedProfile | None:
        """Resolve a profile_id to runtime objects.

        Returns ``None`` when ``profile_id`` is ``None`` or not found in the
        registry — callers fall back to TRACE sample defaults.

        Args:
            profile_id: Identifier registered in the ProfileRegistry, or None.

        Returns:
            ``ResolvedProfile`` with live instances, or ``None``.
        """
        if not profile_id:
            return None

        profile = self._registry.get(profile_id)
        if profile is None:
            logger.warning(
                "ProfileRuntimeResolver.resolve: profile_id=%r not found in registry. "
                "Falling back to TRACE sample defaults.",
                profile_id,
            )
            return None

        # Build stage graph from factory if provided.
        stage_graph: Any | None = None
        if profile.stage_graph_factory is not None:
            try:
                stage_graph = profile.stage_graph_factory()
                logger.info(
                    "ProfileRuntimeResolver: stage_graph created from factory for profile %r.",
                    profile_id,
                )
            except Exception as exc:
                logger.warning(
                    "ProfileRuntimeResolver: stage_graph_factory failed for %r: %s. "
                    "Falling back to TRACE default graph.",
                    profile_id,
                    exc,
                )

        # Build evaluator from factory if provided.
        evaluator: Any | None = None
        if profile.evaluator_factory is not None:
            try:
                evaluator = profile.evaluator_factory()
                logger.info(
                    "ProfileRuntimeResolver: evaluator created from factory for profile %r.",
                    profile_id,
                )
            except Exception as exc:
                logger.warning(
                    "ProfileRuntimeResolver: evaluator_factory failed for %r: %s. "
                    "No custom evaluator will be used.",
                    profile_id,
                    exc,
                )

        return ResolvedProfile(
            profile_id=profile_id,
            stage_graph=stage_graph,
            stage_actions=dict(profile.stage_actions),
            evaluator=evaluator,
            config_overrides=dict(profile.config_overrides),
            required_capabilities=list(profile.required_capabilities),
        )
