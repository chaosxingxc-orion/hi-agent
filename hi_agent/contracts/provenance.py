"""Provenance data contract — structured source reference for capability outputs."""

from __future__ import annotations

from dataclasses import dataclass


# scope: process-internal — pure value object (CLAUDE.md Rule 12 carve-out)
@dataclass
class Provenance:
    """Structured source reference attached to memory entries and capability outputs.

    Platform defines the contract; business-layer capabilities populate fields.
    All fields are optional (default empty string) to maintain backward compatibility.
    """

    url: str = ""
    title: str = ""
    source_type: str = ""  # "web" | "pdf" | "api" | "user_input" | "llm_inference"
    retrieved_at: str = ""  # ISO 8601 timestamp string
