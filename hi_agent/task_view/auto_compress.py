"""Automatic compression trigger before Task View assembly.

Inspired by claude-code's lazy compaction: check token budget before
each LLM call, trigger compression if needed.
"""

from __future__ import annotations

from typing import Any

from hi_agent.task_view.token_budget import count_tokens


class AutoCompressTrigger:
    """Checks if compression is needed before building context.

    Three-level check (inspired by claude-code):
    1. Snip: If records > snip_threshold, drop oldest non-critical records
    2. Window: If tokens > window_threshold, truncate to fit
    3. Compress: If tokens still > compress_threshold, trigger LLM compression
    """

    def __init__(
        self,
        snip_threshold: int = 50,
        window_threshold: int = 6000,
        compress_threshold: int = 4000,
        compressor: Any | None = None,
    ) -> None:
        """Initialize compression policy controls.

        Parameters
        ----------
        snip_threshold:
            Maximum number of records before oldest non-critical ones are
            dropped (snip level).
        window_threshold:
            Token count above which records are truncated to fit the
            window (window level).
        compress_threshold:
            Token count above which LLM-based compression is triggered
            (compress level).
        compressor:
            Optional :class:`~hi_agent.memory.compressor.MemoryCompressor`.
            When provided and the compress level is reached, the
            compressor is called to produce a summary.
        """
        self.snip_threshold = snip_threshold
        self.window_threshold = window_threshold
        self.compress_threshold = compress_threshold
        self._compressor = compressor

    # -- public API -----------------------------------------------------------

    def should_compress(
        self,
        records: list[dict[str, Any]],
        budget_tokens: int = 8192,
    ) -> str:
        """Return compression level needed: 'none', 'snip', 'window', 'compress'.

        Parameters
        ----------
        records:
            Evidence records to evaluate.
        budget_tokens:
            Token budget for the context window.

        Returns:
        -------
        str
            One of ``'none'``, ``'snip'``, ``'window'``, ``'compress'``.
        """
        if len(records) > self.snip_threshold:
            return "snip"

        total_tokens = self._estimate_records_tokens(records)

        if total_tokens > self.window_threshold:
            if total_tokens > budget_tokens or (
                self._compressor is not None and total_tokens > self.compress_threshold
            ):
                return "compress"
            return "window"

        return "none"

    def check_and_compress(
        self,
        records: list[dict[str, Any]],
        stage_id: str,
        budget_tokens: int = 8192,
        run_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Check if compression needed. Returns (filtered_records, new_summary_or_None).

        1. Snip: Drop records beyond threshold (keep most recent)
        2. Window: Truncate to fit token budget
        3. Compress: If still over budget and compressor available,
           compress to summary

        Parameters
        ----------
        records:
            Evidence records to potentially compress.
        stage_id:
            Current stage identifier (passed to compressor).
        budget_tokens:
            Token budget for the context window.

        Returns:
        -------
        tuple
            ``(filtered_records, summary_dict_or_None)``
        """
        level = self.should_compress(records, budget_tokens)

        if level == "none":
            return records, None

        working = list(records)

        # Level 1: Snip -- keep only most recent records.
        if len(working) > self.snip_threshold:
            working = working[-self.snip_threshold :]

        # Level 2: Window -- truncate to fit token budget.
        total = self._estimate_records_tokens(working)
        if total > budget_tokens:
            working = self._window_truncate(working, budget_tokens)

        # Level 3: Compress -- if still over compress_threshold and
        # compressor is available, produce an LLM summary.
        total = self._estimate_records_tokens(working)
        if total > self.compress_threshold and self._compressor is not None:
            summary = self._run_compressor(working, stage_id, run_id=run_id)
            return working, summary

        return working, None

    # -- internal helpers -----------------------------------------------------

    @staticmethod
    def _estimate_records_tokens(records: list[dict[str, Any]]) -> int:
        """Estimate total tokens across all records."""
        total = 0
        for rec in records:
            total += count_tokens(str(rec))
        return total

    def _window_truncate(
        self,
        records: list[dict[str, Any]],
        budget_tokens: int,
    ) -> list[dict[str, Any]]:
        """Keep most recent records that fit within *budget_tokens*."""
        # Walk backward, accumulating tokens.
        kept: list[dict[str, Any]] = []
        used = 0
        for rec in reversed(records):
            cost = count_tokens(str(rec))
            if used + cost > budget_tokens:
                break
            kept.append(rec)
            used += cost
        kept.reverse()
        return kept

    def _run_compressor(
        self,
        records: list[dict[str, Any]],
        stage_id: str,
        *,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Call compressor synchronously and return summary dict.

        Falls back to a simple truncation summary if the compressor
        raises an exception.
        """
        try:
            from hi_agent.memory.l0_raw import RawEventRecord

            raw_records = []
            for rec in records:
                raw_records.append(
                    RawEventRecord(
                        event_type=rec.get("event_type", "unknown"),
                        payload=rec.get("payload", {}),
                        tags=rec.get("tags", []),
                    )
                )

            result = self._compressor.compress_stage(stage_id, raw_records, run_id=run_id)
            return {
                "stage_id": result.stage_id,
                "findings": result.findings,
                "decisions": result.decisions,
                "outcome": result.outcome,
                "compression_method": result.compression_method,
            }
        except Exception:
            self._record_fallback(
                run_id=run_id,
                stage_id=stage_id,
                reason="auto_compress_exception",
                extra={
                    "site": "auto_compress._run_compressor",
                    "record_count": len(records),
                },
            )
            # Fallback: return a minimal summary from the records.
            return {
                "stage_id": stage_id,
                "findings": [str(r) for r in records[-5:]],
                "decisions": [],
                "outcome": "compressed_fallback",
                "compression_method": "auto_fallback",
            }

    def _record_fallback(
        self,
        *,
        run_id: str | None,
        stage_id: str,
        reason: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Best-effort fallback event for auto-compress degradation paths."""
        try:
            from hi_agent.observability.fallback import record_fallback

            record_fallback(
                "heuristic",
                reason=reason,
                run_id=run_id or "unknown_run",
                extra={"stage_id": stage_id, **(extra or {})},
            )
        except Exception:
            pass
