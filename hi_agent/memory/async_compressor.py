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
    NextSteps) for richer, loss-resistant summarization. If StructuredCompressor
    is unavailable or fails, the original LLM or concat path is used as fallback.
    """

    def __init__(
        self,
        gateway: Any | None = None,  # AsyncLLMGateway or LLMGateway
        model: str = "default",
        max_summary_tokens: int = 512,
        *,
        compression_model: str | None = None,
    ) -> None:
        """Initialize AsyncMemoryCompressor.

        ``compression_model`` (when provided) overrides ``model`` for LLM
        calls and is also propagated to :class:`StructuredCompressor` via
        ``StructuredCompressorConfig.model_tier``. It exists so the
        SystemBuilder can pin compression to a concrete coding-plan-served
        model (DF-34).
        """
        self._gateway = gateway
        self._model = compression_model if compression_model is not None else model
        self._compression_model = compression_model
        self._max_summary_tokens = max_summary_tokens
        # Holds the StructuredSummary from the last successful structured compression
        # so that subsequent calls can perform incremental updates.
        self._last_structured_summary: Any = None

    def _emit_fallback(
        self,
        input_text: str,
        records: list[dict[str, Any]],
        *,
        run_id: str | None = None,
        reason: str = "gateway_unavailable",
    ) -> CompressionResult:
        """Execute fallback compression and emit metrics.

        This is the unified fallback path used when StructuredCompressor is unavailable,
        when the gateway is missing, or when LLM compression fails. It uses simple
        string concatenation and emits a warning so operators can track fallback usage.
        """
        global _fallback_count
        _fallback_count += 1

        summary = self._fallback_compress(records)
        logger.warning(
            "Using fallback compression (count: %d, reason=%s): summary length=%d bytes",
            _fallback_count,
            reason,
            len(summary),
        )
        self._record_fallback_event(
            site="async_compressor.compress",
            reason=reason,
            run_id=run_id,
            kind="heuristic",
            extra={
                "fallback_count": _fallback_count,
                "record_count": len(records),
            },
        )
        return CompressionResult(
            summary=summary,
            input_tokens=len(input_text.split()),
            output_tokens=len(summary.split()),
            compression_ratio=len(summary) / max(len(input_text), 1),
        )

    def _record_fallback_event(
        self,
        *,
        site: str,
        reason: str,
        run_id: str | None,
        kind: str = "heuristic",
        error: BaseException | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Emit a structured fallback signal for a silent degradation path."""
        try:
            from hi_agent.observability.fallback import record_fallback

            event_extra = {"site": site, **(extra or {})}
            if error is not None:
                event_extra.setdefault("error_type", type(error).__name__)
                event_extra.setdefault("error", str(error)[:200])
            record_fallback(
                kind,
                reason=reason,
                run_id=run_id or "unknown",
                extra=event_extra,
            )
        except Exception:  # rule7-exempt: expiry_wave="Wave 21"
            pass  # metrics must not crash caller — observability is best-effort

    async def compress(
        self,
        records: list[dict[str, Any]],
        context: str = "",
        *,
        run_id: str | None = None,
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
            return self._emit_fallback(
                input_text,
                records,
                run_id=run_id,
                reason="gateway_unavailable",
            )

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
                    model_tier=(
                        self._compression_model
                        if self._compression_model is not None
                        else "light"
                    ),
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
            except ImportError as exc:
                logger.debug("StructuredCompressor not available; proceeding to LLM fallback")
                self._record_fallback_event(
                    site="async_compressor.compress.structured_import",
                    reason="structured_compressor_unavailable",
                    run_id=run_id,
                    error=exc,
                )
            except Exception as exc:
                logger.warning(
                    "StructuredCompressor failed, falling back to plain LLM compression: %s",
                    exc,
                )
                self._record_fallback_event(
                    site="async_compressor.compress.structured_compress",
                    reason="structured_compressor_error",
                    run_id=run_id,
                    kind="llm",
                    error=exc,
                )

        # LLM-powered compression (original path)
        if complete is None:
            # If gateway lacks complete method, fall back to string concatenation
            return self._emit_fallback(
                input_text,
                records,
                run_id=run_id,
                reason="gateway_missing_complete",
            )

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
