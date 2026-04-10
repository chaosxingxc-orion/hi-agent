"""Async memory compressor with LLM-powered summarization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hi_agent.llm.protocol import LLMRequest


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

        # Build input text
        input_text = self._build_input(records, context)
        input_tokens = len(input_text.split())  # rough estimate

        if self._gateway is None:
            # Fallback: simple concat (same as sync compressor)
            summary = self._fallback_compress(records)
            return CompressionResult(
                summary=summary,
                input_tokens=input_tokens,
                output_tokens=len(summary.split()),
                compression_ratio=len(summary) / max(len(input_text), 1),
            )

        # LLM-powered compression
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
        import inspect

        complete = getattr(self._gateway, "complete", None)
        if complete is None:
            summary = self._fallback_compress(records)
            return CompressionResult(
                summary=summary,
                input_tokens=input_tokens,
                output_tokens=len(summary.split()),
                compression_ratio=len(summary) / max(len(input_text), 1),
            )

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
