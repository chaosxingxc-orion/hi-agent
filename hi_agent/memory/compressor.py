"""Memory compressor utilities with async LLM compression and fallback."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hi_agent.llm.protocol import LLMGateway, LLMRequest
from hi_agent.memory.compress_prompts import STAGE_COMPRESSION_PROMPT
from hi_agent.memory.l0_raw import RawEventRecord
from hi_agent.memory.l1_compressed import CompressedStageMemory

logger = logging.getLogger(__name__)


@dataclass
class CompressionMetrics:
    """Track compression statistics."""

    compressed_count: int = 0
    fallback_count: int = 0
    direct_count: int = 0
    _ratios: list[float] = field(default_factory=list)

    @property
    def avg_compression_ratio(self) -> float:
        """Average ratio of output items to input evidence count."""
        if not self._ratios:
            return 0.0
        return sum(self._ratios) / len(self._ratios)

    def record(
        self,
        method: str,
        input_count: int,
        output_items: int,
    ) -> None:
        """Record one compression event."""
        if method == "llm":
            self.compressed_count += 1
        elif method == "fallback":
            self.fallback_count += 1
        else:
            self.direct_count += 1
        if input_count > 0:
            self._ratios.append(output_items / input_count)


class MemoryCompressor:
    """Compress L0 records into L1 stage summary.

    Supports three modes:
    - **direct**: when evidence count < *compress_threshold*, build summary
      deterministically without an LLM call.
    - **llm**: when evidence count >= threshold, call *llm_fn* with a
      structured prompt and parse the JSON result.
    - **fallback**: on LLM timeout / error, truncate to last *fallback_items*
      records and build summary deterministically.
    """

    def __init__(
        self,
        llm_fn: Callable[..., Any] | None = None,
        timeout_s: float = 10.0,
        compress_threshold: int = 25,
        fallback_items: int = 20,
        *,
        gateway: LLMGateway | None = None,
        max_findings: int = 8,
        max_decisions: int = 8,
        max_entities: int = 10,
        max_tokens: int = 2048,
        compression_model: str | None = None,
    ) -> None:
        """Initialize compression policy controls.

        Parameters
        ----------
        llm_fn:
            Async callable ``(prompt: str) -> str``.  When *None* the
            compressor always uses the deterministic path (unless *gateway*
            is provided).
        timeout_s:
            Maximum seconds to wait for *llm_fn* or gateway call.
        compress_threshold:
            Evidence count at which the LLM path is attempted.
        fallback_items:
            Number of most-recent records kept when falling back.
        gateway:
            Optional :class:`LLMGateway`.  When provided, takes precedence
            over *llm_fn* for LLM compression calls.
        max_findings:
            Maximum findings to keep in direct-path summary (default 8).
        max_decisions:
            Maximum decisions to keep in direct-path summary (default 8).
        max_entities:
            Maximum key entities to keep in direct-path summary (default 10).
        max_tokens:
            Maximum tokens for LLM compression prompt response (default 2048).
        compression_model:
            Optional concrete model identifier (e.g. ``"glm-5.1"``) passed as
            ``LLMRequest.model`` for compression calls.  When ``None``, the
            legacy tier label ``"light"`` is used so gateway tier routing picks
            the configured light-tier model.  Pinning is used by the default
            builder to avoid coding-plan endpoints rejecting the light tier
            with ``UnsupportedModel`` (DF-34).
        """
        self.llm_fn = llm_fn
        self._gateway = gateway
        self.timeout_s = timeout_s
        self.compress_threshold = compress_threshold
        self.fallback_items = fallback_items
        self.max_findings = max_findings
        self.max_decisions = max_decisions
        self.max_entities = max_entities
        self.max_tokens = max_tokens
        self._compression_model = compression_model
        self.metrics = CompressionMetrics()

    # -- public entry points --------------------------------------------------

    def compress_stage(
        self,
        stage_id: str,
        records: list[RawEventRecord],
        *,
        run_id: str | None = None,
    ) -> CompressedStageMemory:
        """Synchronous entry point (backward-compatible).

        Delegates to :meth:`_build_summary_from_raw` for below-threshold
        evidence.  For above-threshold evidence, uses the gateway if
        available (synchronous call), otherwise falls back to truncation.
        """
        if len(records) < self.compress_threshold:
            result = self._build_summary_from_raw(stage_id, records)
            self.metrics.record(
                "direct",
                len(records),
                len(result.findings) + len(result.decisions),
            )
            return result

        if self._gateway is not None:
            try:
                result = self._gateway_compress_sync(stage_id, records)
                self.metrics.record(
                    "llm",
                    len(records),
                    len(result.findings) + len(result.decisions),
                )
                return result
            except Exception as exc:
                logger.warning(
                    "MemoryCompressor: sync LLM compression failed, using fallback: %s", exc
                )
                self._record_fallback_event(
                    run_id=run_id,
                    stage_id=stage_id,
                    site="memory_compressor.compress_stage",
                    exc=exc,
                )
                # fall through to fallback

        result = self._fallback_truncate(stage_id, records)
        self.metrics.record(
            "fallback",
            len(records),
            len(result.findings) + len(result.decisions),
        )
        return result

    async def acompress_stage(
        self,
        stage_id: str,
        records: list[RawEventRecord],
        *,
        run_id: str | None = None,
    ) -> CompressedStageMemory:
        """Compress *records* for *stage_id* into a :class:`CompressedStageMemory`."""
        if len(records) < self.compress_threshold:
            result = self._build_summary_from_raw(stage_id, records)
            self.metrics.record(
                "direct",
                len(records),
                len(result.findings) + len(result.decisions),
            )
            return result

        if self._gateway is not None:
            try:
                result = await asyncio.wait_for(
                    self._gateway_compress(stage_id, records),
                    timeout=self.timeout_s,
                )
                self.metrics.record(
                    "llm",
                    len(records),
                    len(result.findings) + len(result.decisions),
                )
                return result
            except (TimeoutError, Exception) as exc:
                logger.warning(
                    "MemoryCompressor: gateway async compression failed, using fallback: %s", exc
                )
                self._record_fallback_event(
                    run_id=run_id,
                    stage_id=stage_id,
                    site="memory_compressor.acompress_stage.gateway",
                    exc=exc,
                )
                result = self._fallback_truncate(stage_id, records)
                self.metrics.record(
                    "fallback",
                    len(records),
                    len(result.findings) + len(result.decisions),
                )
                return result

        if self.llm_fn is not None:
            try:
                result = await asyncio.wait_for(
                    self._llm_compress(stage_id, records),
                    timeout=self.timeout_s,
                )
                self.metrics.record(
                    "llm",
                    len(records),
                    len(result.findings) + len(result.decisions),
                )
                return result
            except (TimeoutError, Exception) as exc:
                logger.warning(
                    "MemoryCompressor: llm_fn async compression failed, using fallback: %s", exc
                )
                self._record_fallback_event(
                    run_id=run_id,
                    stage_id=stage_id,
                    site="memory_compressor.acompress_stage.llm_fn",
                    exc=exc,
                )
                result = self._fallback_truncate(stage_id, records)
                self.metrics.record(
                    "fallback",
                    len(records),
                    len(result.findings) + len(result.decisions),
                )
                return result

        # No gateway and no llm_fn - deterministic fallback
        result = self._fallback_truncate(stage_id, records)
        self.metrics.record(
            "fallback",
            len(records),
            len(result.findings) + len(result.decisions),
        )
        return result

    # -- synchronous convenience alias ----------------------------------------

    def compress_stage_sync(
        self,
        stage_id: str,
        records: list[RawEventRecord],
        *,
        run_id: str | None = None,
    ) -> CompressedStageMemory:
        """Alias for :meth:`compress_stage` (sync)."""
        return self.compress_stage(stage_id, records, run_id=run_id)

    # -- internal helpers -----------------------------------------------------

    def _record_fallback_event(
        self,
        *,
        run_id: str | None,
        stage_id: str,
        site: str,
        exc: BaseException,
    ) -> None:
        try:
            from hi_agent.observability.fallback import record_fallback

            reason = (
                "llm_json_parse_error"
                if isinstance(exc, json.JSONDecodeError)
                else "llm_compression_failed"
            )
            record_fallback(
                "heuristic",
                reason=reason,
                run_id=run_id or "unknown",
                extra={
                    "site": site,
                    "stage_id": stage_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:200],
                },
            )
        except Exception:
            pass  # metrics must not crash caller — observability is best-effort

    def _build_summary_from_raw(
        self,
        stage_id: str,
        records: list[RawEventRecord],
    ) -> CompressedStageMemory:
        """Extract findings, decisions, outcome from raw records without LLM."""
        findings: list[str] = []
        decisions: list[str] = []
        key_entities: list[str] = []
        contradiction_refs: list[str] = []

        for record in records:
            if record.event_type == "StageStateChanged":
                sid = record.payload.get("stage_id", "")
                to_state = record.payload.get("to_state", "")
                findings.append(f"{sid}:{to_state}")
                if sid and sid not in key_entities:
                    key_entities.append(sid)
            if record.event_type == "TaskViewRecorded":
                decisions.append(f"task_view:{record.payload.get('task_view_id')}")
            for tag in getattr(record, "tags", []):
                if tag.startswith("contradiction:"):
                    contradiction_refs.append(tag)

        if any("failed" in item for item in findings):
            outcome = "failed"
        elif any("completed" in item for item in findings):
            outcome = "succeeded"
        else:
            outcome = "active"

        return CompressedStageMemory(
            stage_id=stage_id,
            findings=findings[: self.max_findings],
            decisions=decisions[: self.max_decisions],
            outcome=outcome,
            contradiction_refs=contradiction_refs,
            key_entities=key_entities[: self.max_entities],
            source_evidence_count=len(records),
            compression_method="direct",
        )

    async def _gateway_compress(
        self,
        stage_id: str,
        records: list[RawEventRecord],
    ) -> CompressedStageMemory:
        """Use :class:`LLMGateway` to compress evidence into structured summary."""
        evidence_lines: list[str] = []
        for idx, rec in enumerate(records):
            evidence_lines.append(f"[{idx}] {rec.event_type}: {json.dumps(rec.payload)}")
        evidence_text = "\n".join(evidence_lines)

        user_prompt = STAGE_COMPRESSION_PROMPT.format(
            stage_id=stage_id,
            evidence_count=len(records),
            evidence_text=evidence_text,
        )

        request = LLMRequest(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a memory compression engine for the TRACE framework. "
                        "Compress stage execution evidence into a structured JSON summary."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            model=self._compression_model if self._compression_model is not None else "light",
            temperature=0.2,
            max_tokens=self.max_tokens,
            metadata={
                "stage_id": stage_id,
                "evidence_count": len(records),
                "purpose": "memory_compression",
            },
        )

        # Gateway.complete is synchronous; run in executor to keep async contract
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            self._gateway.complete,
            request,  # type: ignore[union-attr]
        )
        parsed = json.loads(response.content)

        return CompressedStageMemory(
            stage_id=stage_id,
            findings=parsed.get("findings", []),
            decisions=parsed.get("decisions", []),
            outcome=parsed.get("outcome", "inconclusive"),
            contradiction_refs=parsed.get("contradiction_refs", []),
            key_entities=parsed.get("key_entities", []),
            source_evidence_count=len(records),
            compression_method="llm",
        )

    def _gateway_compress_sync(
        self,
        stage_id: str,
        records: list[RawEventRecord],
    ) -> CompressedStageMemory:
        """Synchronous gateway compression (for :meth:`compress_stage`)."""
        evidence_lines: list[str] = []
        for idx, rec in enumerate(records):
            evidence_lines.append(f"[{idx}] {rec.event_type}: {json.dumps(rec.payload)}")
        evidence_text = "\n".join(evidence_lines)

        user_prompt = STAGE_COMPRESSION_PROMPT.format(
            stage_id=stage_id,
            evidence_count=len(records),
            evidence_text=evidence_text,
        )

        request = LLMRequest(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a memory compression engine for the TRACE framework. "
                        "Compress stage execution evidence into a structured JSON summary."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            model=self._compression_model if self._compression_model is not None else "light",
            temperature=0.2,
            max_tokens=self.max_tokens,
            metadata={
                "stage_id": stage_id,
                "evidence_count": len(records),
                "purpose": "memory_compression",
            },
        )

        response = self._gateway.complete(request)  # type: ignore[union-attr]
        parsed = json.loads(response.content)

        return CompressedStageMemory(
            stage_id=stage_id,
            findings=parsed.get("findings", []),
            decisions=parsed.get("decisions", []),
            outcome=parsed.get("outcome", "inconclusive"),
            contradiction_refs=parsed.get("contradiction_refs", []),
            key_entities=parsed.get("key_entities", []),
            source_evidence_count=len(records),
            compression_method="llm",
        )

    async def _llm_compress(
        self,
        stage_id: str,
        records: list[RawEventRecord],
    ) -> CompressedStageMemory:
        """Use LLM to compress evidence into structured summary."""
        evidence_lines: list[str] = []
        for idx, rec in enumerate(records):
            evidence_lines.append(f"[{idx}] {rec.event_type}: {json.dumps(rec.payload)}")
        evidence_text = "\n".join(evidence_lines)

        prompt = STAGE_COMPRESSION_PROMPT.format(
            stage_id=stage_id,
            evidence_count=len(records),
            evidence_text=evidence_text,
        )

        raw_response = await self.llm_fn(prompt)  # type: ignore[misc]
        parsed = json.loads(raw_response)

        return CompressedStageMemory(
            stage_id=stage_id,
            findings=parsed.get("findings", []),
            decisions=parsed.get("decisions", []),
            outcome=parsed.get("outcome", "inconclusive"),
            contradiction_refs=parsed.get("contradiction_refs", []),
            key_entities=parsed.get("key_entities", []),
            source_evidence_count=len(records),
            compression_method="llm",
        )

    def _fallback_truncate(
        self,
        stage_id: str,
        records: list[RawEventRecord],
        max_items: int | None = None,
    ) -> CompressedStageMemory:
        """Take last *max_items* records and build summary deterministically."""
        limit = max_items if max_items is not None else self.fallback_items
        truncated = records[-limit:]
        result = self._build_summary_from_raw(stage_id, truncated)
        result.compression_method = "fallback"
        result.source_evidence_count = len(records)
        return result
