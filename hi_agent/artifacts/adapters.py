"""OutputToArtifactAdapter — normalize capability outputs to typed Artifacts.

Capability handlers return raw ``dict`` outputs.  This adapter infers the
best ``Artifact`` subclass from the output's structure and creates a typed
artifact for persistent storage.

Inference rules (first match wins):
- Has ``url`` + ``title``                         → ``ResourceArtifact``
- Has ``claim`` + ``confidence``                  → ``EvidenceArtifact``
- Has ``score`` + ``passed``                      → ``EvaluationArtifact``
- Has ``data`` + ``schema_id``                    → ``StructuredDataArtifact``
- Has ``url`` only (no title)                     → ``DocumentArtifact``
- Everything else                                 → ``Artifact`` (base)
"""

from __future__ import annotations

import logging
from typing import Any

from hi_agent.artifacts.contracts import (
    Artifact,
    DocumentArtifact,
    EvaluationArtifact,
    EvidenceArtifact,
    ResourceArtifact,
    StructuredDataArtifact,
)

logger = logging.getLogger(__name__)


class OutputToArtifactAdapter:
    """Convert a raw capability output dict into one or more typed Artifacts."""

    def adapt(
        self,
        action_id: str,
        output: Any,
        *,
        source_refs: list[str] | None = None,
    ) -> list[Artifact]:
        """Infer artifact type(s) from output and return typed instances.

        Args:
            action_id: The action that produced this output (becomes
                ``producer_action_id`` on the artifact).
            output: Raw capability output.  Non-dict outputs are wrapped in
                ``{"output": output}`` before inference.
            source_refs: Optional upstream artifact IDs.

        Returns:
            A list of typed ``Artifact`` instances (usually one).
        """
        if output is None:
            return []

        if not isinstance(output, dict):
            output = {"output": output}

        refs = source_refs or []
        artifact = self._infer(output, action_id, refs)
        logger.debug(
            "OutputToArtifactAdapter: action=%r → %s",
            action_id,
            type(artifact).__name__,
        )
        return [artifact]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _infer(
        self, output: dict[str, Any], action_id: str, source_refs: list[str]
    ) -> Artifact:
        common = {
            "producer_action_id": action_id,
            "source_refs": source_refs,
            "upstream_artifact_ids": source_refs,
            "provenance": {"capability_action_id": action_id, "adapter": "OutputToArtifactAdapter"},
        }

        if "url" in output and "title" in output:
            return ResourceArtifact(
                url=output["url"],
                title=str(output["title"]),
                snippet=str(output.get("snippet", output.get("text", ""))),
                **common,
            )

        if "claim" in output and "confidence" in output:
            return EvidenceArtifact(
                claim=str(output["claim"]),
                confidence=float(output["confidence"]),
                evidence_type=str(output.get("evidence_type", "direct")),
                **common,
            )

        if "score" in output and "passed" in output:
            return EvaluationArtifact(
                score=float(output["score"]),
                passed=bool(output["passed"]),
                criteria=dict(output.get("criteria_results", output.get("criteria", {}))),
                feedback=str(output.get("feedback", "")),
                **common,
            )

        if "data" in output and "schema_id" in output:
            return StructuredDataArtifact(
                schema_id=str(output["schema_id"]),
                data=output["data"],
                **common,
            )

        if "url" in output:
            return DocumentArtifact(
                url=output["url"],
                title=str(output.get("title", "")),
                text=str(output.get("text", output.get("content", ""))),
                word_count=int(output.get("word_count", 0)),
                **common,
            )

        # Generic base artifact — preserve raw content.
        return Artifact(content=output, **common)
