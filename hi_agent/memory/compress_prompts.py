"""Prompt templates for LLM-based memory compression."""

from __future__ import annotations

STAGE_COMPRESSION_PROMPT = """\
You are compressing stage execution evidence into a structured summary.

Stage: {stage_id}
Evidence count: {evidence_count}

Evidence:
{evidence_text}

Output a JSON object with exactly these fields:
- findings: list of key findings (strings)
- decisions: list of decisions made (strings)
- outcome: one of "success", "partial", "failure", "inconclusive"
- contradiction_refs: list of evidence indices that contradict each other (empty if none)
- key_entities: list of important entities/concepts mentioned
"""
