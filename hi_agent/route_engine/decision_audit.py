"""Route decision audit helpers."""

from __future__ import annotations

from collections.abc import Callable
from time import time
from typing import Any


def record_route_decision_audit(
    *,
    run_id: str,
    stage_id: str,
    engine: str,
    provenance: str,
    selected_branch: str,
    candidates: list[dict[str, Any]] | None = None,
    confidence: float | None = None,
    now_fn: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Return normalized audit payload for one route decision."""
    normalized_run_id = run_id.strip()
    normalized_stage_id = stage_id.strip()
    normalized_engine = engine.strip()
    normalized_provenance = provenance.strip()
    normalized_selected_branch = selected_branch.strip()

    if not normalized_run_id:
        raise ValueError("run_id must be a non-empty string")
    if not normalized_stage_id:
        raise ValueError("stage_id must be a non-empty string")
    if not normalized_engine:
        raise ValueError("engine must be a non-empty string")
    if not normalized_provenance:
        raise ValueError("provenance must be a non-empty string")
    if not normalized_selected_branch:
        raise ValueError("selected_branch must be a non-empty string")

    normalized_confidence: float | None = None
    if confidence is not None:
        normalized_confidence = float(confidence)
        if normalized_confidence < 0.0 or normalized_confidence > 1.0:
            raise ValueError("confidence must be in range [0, 1]")

    normalized_candidates = [dict(item) for item in (candidates or [])]
    return {
        "run_id": normalized_run_id,
        "stage_id": normalized_stage_id,
        "engine": normalized_engine,
        "provenance": normalized_provenance,
        "confidence": normalized_confidence,
        "selected_branch": normalized_selected_branch,
        "candidates": normalized_candidates,
        "ts": float((now_fn or time)()),
    }


def is_low_confidence(audit: dict[str, Any], threshold: float = 0.7) -> bool:
    """Return true if audit confidence is below threshold."""
    if threshold < 0.0 or threshold > 1.0:
        raise ValueError("threshold must be in range [0, 1]")
    confidence = audit.get("confidence")
    if confidence is None:
        return False
    value = float(confidence)
    if value < 0.0 or value > 1.0:
        raise ValueError("audit confidence must be in range [0, 1]")
    return value < threshold


def persist_route_decision_audit(
    store: object,
    *,
    run_id: str,
    stage_id: str,
    engine: str,
    provenance: str,
    selected_branch: str,
    candidates: list[dict[str, Any]] | None = None,
    confidence: float | None = None,
    now_fn: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Create and persist one route decision audit record."""
    append = getattr(store, "append", None)
    if not callable(append):
        raise TypeError("store must provide callable append(audit)")

    audit = record_route_decision_audit(
        run_id=run_id,
        stage_id=stage_id,
        engine=engine,
        provenance=provenance,
        selected_branch=selected_branch,
        candidates=candidates,
        confidence=confidence,
        now_fn=now_fn,
    )
    append(audit)
    return audit
