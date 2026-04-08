"""Perception middleware: input parsing, entity extraction, summarization.

Does NOT do intent recognition (that's business logic for Control).
Only does standard NLP-style processing:
  1. Multimodal input -> unified text representation
  2. Entity extraction (names, dates, numbers, code blocks, URLs)
  3. Summarization (if input exceeds threshold)
  4. Context assembly (within token budget via ContextManager)
  5. Metadata annotation (modality, language, token_count)
"""
from __future__ import annotations

import re
from typing import Any

from hi_agent.middleware.protocol import (
    Entity,
    MiddlewareMessage,
    PerceptionResult,
)
from typing import Any


# Regex patterns for entity extraction
_DATE_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DATE_NATURAL = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{4})?\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_URL = re.compile(r"https?://[^\s)<>\"]+")
_EMAIL = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_CODE_BLOCK = re.compile(r"```[\s\S]*?```")

_IMAGE_MARKERS = ("[image:", "data:image/", "<img ")
_AUDIO_MARKERS = ("[audio:", "data:audio/", "<audio ")


class PerceptionMiddleware:
    """Standard input processing middleware."""

    def __init__(
        self,
        context_manager: Any | None = None,
        summary_threshold: int = 2000,  # tokens above which to summarize
        max_entities: int = 50,
    ) -> None:
        self._context_manager = context_manager
        self._summary_threshold = summary_threshold
        self._max_entities = max_entities

    @property
    def name(self) -> str:
        return "perception"

    def on_create(self, config: dict[str, Any]) -> None:
        """Configure from external config dict."""
        if "summary_threshold" in config:
            self._summary_threshold = config["summary_threshold"]
        if "max_entities" in config:
            self._max_entities = config["max_entities"]

    def on_destroy(self) -> None:
        """Cleanup resources."""
        self._context_manager = None

    def process(self, message: MiddlewareMessage) -> MiddlewareMessage:
        """Parse input -> extract entities -> summarize if needed -> assemble context."""
        raw_input = message.payload.get("user_input", "")

        text, modality = self._parse_input(raw_input)
        entities = self._extract_entities(text)
        summary = self._summarize_if_needed(text, self._summary_threshold)
        context = self._assemble_context(text, entities)

        # Estimate token count (~4 chars per token)
        token_count = max(1, len(text) // 4)

        result = PerceptionResult(
            raw_text=text,
            entities=entities,
            summary=summary,
            modality=modality,
            context=context,
            token_count=token_count,
            metadata=message.metadata,
        )

        return MiddlewareMessage(
            source="perception",
            target="control",
            msg_type="perception_result",
            payload={
                "raw_text": result.raw_text,
                "entities": [
                    {"entity_type": e.entity_type, "value": e.value, "position": e.position}
                    for e in result.entities
                ],
                "summary": result.summary,
                "modality": result.modality,
                "context": result.context,
                "token_count": result.token_count,
            },
            token_cost=token_count,
            metadata=result.metadata,
        )

    def _parse_input(self, raw_input: str) -> tuple[str, str]:
        """Parse multimodal input. Returns (text, modality)."""
        if not raw_input:
            return "", "text"

        has_image = any(marker in raw_input.lower() for marker in _IMAGE_MARKERS)
        has_audio = any(marker in raw_input.lower() for marker in _AUDIO_MARKERS)

        if has_image and has_audio:
            modality = "multimodal"
        elif has_image:
            modality = "image"
        elif has_audio:
            modality = "audio"
        else:
            modality = "text"

        return raw_input, modality

    def _extract_entities(self, text: str) -> list[Entity]:
        """Extract entities using regex patterns.
        Patterns: dates (ISO/natural), numbers, URLs, code blocks, emails."""
        if not text:
            return []

        entities: list[Entity] = []

        # Code blocks first (remove them from number/date scanning to avoid noise)
        for m in _CODE_BLOCK.finditer(text):
            entities.append(Entity(
                entity_type="code_block", value=m.group(), position=m.start(),
            ))

        # URLs
        for m in _URL.finditer(text):
            entities.append(Entity(
                entity_type="url", value=m.group(), position=m.start(),
            ))

        # Emails
        for m in _EMAIL.finditer(text):
            entities.append(Entity(
                entity_type="email", value=m.group(), position=m.start(),
            ))

        # ISO dates
        for m in _DATE_ISO.finditer(text):
            entities.append(Entity(
                entity_type="date", value=m.group(), position=m.start(),
            ))

        # Natural dates
        for m in _DATE_NATURAL.finditer(text):
            entities.append(Entity(
                entity_type="date", value=m.group(), position=m.start(),
            ))

        # Numbers (exclude those already part of dates/URLs)
        existing_positions = {(e.position, e.position + len(e.value)) for e in entities}
        for m in _NUMBER.finditer(text):
            start, end = m.start(), m.end()
            # Skip if overlapping with existing entity
            overlaps = any(
                not (end <= es or start >= ee) for es, ee in existing_positions
            )
            if not overlaps:
                entities.append(Entity(
                    entity_type="number", value=m.group(), position=start,
                ))

        # Sort by position, limit to max_entities
        entities.sort(key=lambda e: e.position)
        return entities[: self._max_entities]

    def _summarize_if_needed(self, text: str, threshold: int) -> str | None:
        """Summarize text if it exceeds token threshold.
        Without LLM: extractive (first + last paragraphs + key sentences).
        With LLM: abstractive via ContextManager's compressor."""
        if not text:
            return None

        estimated_tokens = len(text) // 4
        if estimated_tokens <= threshold:
            return None

        # Extractive summarization: first paragraph + last paragraph
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            return text[:threshold * 4]

        parts: list[str] = []
        if paragraphs:
            parts.append(paragraphs[0])
        if len(paragraphs) > 1:
            parts.append(paragraphs[-1])

        return "\n\n".join(parts)

    def _assemble_context(self, text: str, entities: list[Entity]) -> str:
        """Assemble session context within budget using ContextManager."""
        if self._context_manager is not None:
            try:
                snapshot = self._context_manager.prepare_context(
                    purpose="perception",
                    extra_context={"current_input": text},
                )
                return snapshot.to_prompt_string()
            except Exception:
                pass

        # Fallback: just return the text
        return text
