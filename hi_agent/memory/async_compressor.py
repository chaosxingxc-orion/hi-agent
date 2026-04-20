"""Async memory compressor with LLM-powered summarization."""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import Any

from hi_agent.llm.protocol import LLMRequest

logger = logging.getLogger(__name__)

# Track fallback usage
_fallback_count: int = 0


@dataclass
class CompressionResult:
    """Result of async compression."""

    summary: str
    input_tokens: int
    output_tokens: int
    compression_ratio: float


class AsyncMemoryCompressor:
    """LLM-powered memory compressor for L1 summarization.

    Unlike the sync MemoryCompressor (string concat), this version
    uses an LLM to produce semantic summaries of raw memory events.
    Falls back to string concat when no gateway is available.

    When the gateway supports async calls, compression is upgraded to use
    StructuredCompressor (five-field schema: Goal/Progress/Decisions/Files/
    NextSteps) for richer, loss-resistant summarization.  If StructuredCompressor
    is unavailable or fails, the original LLM or concat path is used as fallback.
    """

    def __init__(
        self,
        gateway: Any | None = None,  # AsyncLLMGateway or LLMGateway
        model: str = "default",
        max_summary_tokens: int = 512,
    ) -> None:
        """Initialize AsyncMemoryCompressor."""
        self._gateway = gateway
        self._model = model
        self._max_summary_tokens = max_summary_tokens
        # Holds the StructuredSummary from the last successful structured compression
        # so that subsequent calls can perform incremental updates.
        self._last_structured_summary: Any = None

    def _emit_fallback(self, input_text: str, records: list[dict[str, Any]]) -> CompressionResult:
        """Execute fallback compression and emit metrics.

        This is the unified fallback path used when StructuredCompressor is unavailable,
        when the gateway is missing, or when LLM compression fails. It uses simple
        string concatenation and emits a warning so operators can track fallback usage.
        """
        global _fallback_count
        _fallback_count += 1

        summary = self._fallback_compress(records)
        logger.warning(
            "Using fallback compression (count: %d): summary length=%d bytes",
            _fallback_count,
            len(summary),
        )
        return CompressionResult(
            summary=summary,
            input_tokens=len(input_text.split()),
            output_tokens=len(summary.split()),
            compression_ratio=len(summary) / max(len(input_text), 1),
        )

    async def compress(
        self,
        records: list[dict[str, Any]],
        context: str = "",
    ) -> CompressionResult:
        """Compress a list of memory records into a summary.

        Args:
            records: Raw event records to compress.
            context: Optional context string (stage, goal, etc.).

        Returns:
            CompressionResult with summary text and token usage.
        """
        if not records:
            return CompressionResult(
                summary="", input_tokens=0, output_tokens=0, compression_ratio=1.0
            )

        # Build input text (used for token estimation and fallback paths)
        input_text = self._build_input(records, context)
        input_tokens = len(input_text.split())  # rough estimate

        if self._gateway is None:
            # Fallback: simple concat (same as sync compressor)
            return self._emit_fallback(input_text, records)

        # Attempt structured compression when the gateway supports async calls.
        complete = getattr(self._gateway, "complete", None)
        if complete is not None and inspect.iscoroutinefunction(complete):
            try:
                from hi_agent.memory.structured_compression import (
                    StructuredCompressor,
                    StructuredCompressorConfig,
                )

                config = StructuredCompressorConfig(
                    head_count=3,
                    tail_token_budget=4000,
                    model_tier="light",
                )
                s_compressor = StructuredCompressor(self._gateway, config)

                # Convert memory records to message-like dicts that
                # StructuredCompressor understands (role + content).
                messages = self._records_to_messages(records, context)

                _, summary_obj = await s_compressor.compress(
                    messages,
                    existing_summary=self._last_structured_summary,
                )

                # Persist summary for incremental updates on the next call.
                self._last_structured_summary = summary_obj

                # Render the structured summary as the canonical summary string.
                summary_text = summary_obj.to_context_block()

                original_len = len(input_text)
                new_len = len(summary_text)
                return CompressionResult(
                    summary=summary_text,
                    input_tokens=input_tokens,
                    output_tokens=len(summary_text.split()),
                    compression_ratio=new_len / max(original_len, 1),
                )
            except ImportError:
                # structured_compression module not available — fall through
                logger.debug("StructuredCompressor not available; proceeding to LLM fallback")
            except Exception as exc:
                logger.warning(
                    "StructuredCompressor failed, falling back to plain LLM compression: %s",
                    exc,
                )

        # LLM-powered compression (original path)
        if complete is None:
            # If gateway lacks complete method, fall back to string concatenation
            return self._emit_fallback(input_text, records)

        request = LLMRequest(
            messages=[
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": input_text},
            ],
            model=self._model,
            temperature=0.3,
            max_tokens=self._max_summary_tokens,
        )

        import asyncio

        if inspect.iscoroutinefunction(complete):
            response = await complete(request)
        else:
            response = await asyncio.to_thread(complete, request)

        summary = response.content.strip()
        return CompressionResult(
            summary=summary,
            input_tokens=response.usage.prompt_tokens or input_tokens,
            output_tokens=response.usage.completion_tokens or len(summary.split()),
            compression_ratio=len(summary) / max(len(input_text), 1),
        )

    def _records_to_messages(self, records: list[dict[str, Any]], context: str) -> list[dict]:
        """Convert memory event records to message-like dicts for StructuredCompressor.

        Each record becomes a ``user`` message whose content describes the event.
        If a context string is present it is prepended as a ``system`` message so
        the compressor has goal/stage information available.
        """
        messages: list[dict] = []
        if context:
            messages.append({"role": "system", "content": f"Context: {context}"})
        for i, record in enumerate(records, 1):
            event_type = record.get("event_type", "unknown")
            payload = record.get("payload", record)
            content = f"{i}. [{event_type}] {payload}"
            messages.append({"role": "user", "content": content})
        return messages

    def _system_prompt(self) -> str:
        """Run _system_prompt."""
        return (
            "You are a memory compression agent. Summarize the following events "
            "into a concise, information-dense summary that preserves key decisions, "
            "outcomes, and context needed for future reasoning. Be brief."
        )

    def _build_input(self, records: list[dict[str, Any]], context: str) -> str:
        """Run _build_input."""
        parts: list[str] = []
        if context:
            parts.append(f"Context: {context}")
        for i, record in enumerate(records, 1):
            event_type = record.get("event_type", "unknown")
            payload = record.get("payload", record)
            parts.append(f"{i}. [{event_type}] {payload}")
        return "\n".join(parts)

    def _fallback_compress(self, records: list[dict[str, Any]]) -> str:
        """Simple string concatenation fallback."""
        parts: list[str] = []
        for record in records:
            event_type = record.get("event_type", "unknown")
            payload = record.get("payload", "")
            parts.append(f"[{event_type}] {payload}")
        return "; ".join(parts)
