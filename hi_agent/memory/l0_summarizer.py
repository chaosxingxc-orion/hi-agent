"""L0 → L2 summarizer: structured extraction from raw JSONL to DailySummary.

No LLM is used — extraction is rule-based over the event_type field.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from hi_agent.memory.mid_term import DailySummary

# event_type substrings that carry learnable content
_LEARNING_KEYWORDS = ("stage_complete", "result", "outcome")
# exact event_type values that indicate a completed stage
_STAGE_COMPLETE_TYPE = "stage_complete"
# exact event_type values that indicate a pattern or insight
_PATTERN_TYPES = frozenset(("reflection", "insight", "pattern"))


class L0Summarizer:
    """Extract a DailySummary from an L0 JSONL file without using an LLM."""

    def summarize_run(self, run_id: str, base_dir: Path) -> DailySummary | None:
        """Read L0 JSONL for *run_id* and produce a DailySummary for L2.

        Args:
            run_id: The run identifier (matches the filename stem).
            base_dir: Root directory; the JSONL lives at
                {base_dir}/logs/memory/L0/{run_id}.jsonl.

        Returns:
            A DailySummary, or None if the file does not exist or is empty.
        """
        log_path = base_dir / "logs" / "memory" / "L0" / f"{run_id}.jsonl"
        if not log_path.exists():
            return None

        key_learnings: list[str] = []
        tasks_completed: list[str] = []
        patterns_observed: list[str] = []

        line_count = 0
        with log_path.open(encoding="utf-8") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                line_count += 1
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                metadata = record.get("metadata", {})
                event_type: str = metadata.get("event_type", "").lower()
                content = record.get("content", {})

                # Collect key learnings from informative events
                if any(kw in event_type for kw in _LEARNING_KEYWORDS):
                    text = _extract_text(content)
                    if text:
                        key_learnings.append(text)

                # Stage completions → tasks_completed
                if event_type == _STAGE_COMPLETE_TYPE:
                    stage_name = (
                        content.get("stage_id")
                        or content.get("stage_name")
                        or content.get("stage")
                        or event_type
                    )
                    if stage_name:
                        tasks_completed.append(str(stage_name))

                # Patterns / insights / reflections
                if event_type in _PATTERN_TYPES:
                    text = _extract_text(content)
                    if text:
                        patterns_observed.append(text)

        if line_count == 0:
            return None

        return DailySummary(
            date=datetime.now(UTC).strftime("%Y-%m-%d"),
            key_learnings=key_learnings,
            tasks_completed=tasks_completed,
            patterns_observed=patterns_observed,
        )


def _extract_text(content: object) -> str:
    """Return a human-readable string from a content value."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        # Prefer explicit text fields, then fall back to joining all values
        for key in ("text", "message", "summary", "content", "result", "outcome"):
            val = content.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        # Fallback: join all string values
        parts = [str(v) for v in content.values() if v is not None]
        return " | ".join(parts).strip()
    return ""
