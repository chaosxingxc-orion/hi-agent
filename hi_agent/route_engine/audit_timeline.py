"""Route audit timeline helpers."""

from __future__ import annotations

from typing import Any


def _read_field(item: object, key: str) -> Any:
    """Read one field from dict-like/object-like items."""
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def build_audit_timeline(
    audits: list[object],
    *,
    include_confidence: bool = True,
) -> list[dict[str, object]]:
    """Build normalized timeline rows from route decision audits.

    Rows are stably sorted by timestamp ascending. Missing timestamps are pushed
    to the end while preserving original insertion order.
    """
    rows_with_index: list[tuple[int, float | None, dict[str, object]]] = []
    for index, audit in enumerate(audits):
        ts_value = _read_field(audit, "ts")
        ts: float | None
        if ts_value is None:
            ts = None
        elif isinstance(ts_value, int | float):
            ts = float(ts_value)
        else:
            raise ValueError("ts must be numeric when provided")

        confidence = _read_field(audit, "confidence")
        band = _read_field(audit, "band")
        escalate = bool(_read_field(audit, "escalate"))

        row: dict[str, object] = {
            "ts": ts,
            "stage": _read_field(audit, "stage_id"),
            "branch": _read_field(audit, "selected_branch"),
            "confidence": (
                float(confidence)
                if include_confidence and isinstance(confidence, int | float)
                else None
            ),
            "band": str(band) if include_confidence and band is not None else None,
            "escalate": escalate,
        }
        rows_with_index.append((index, ts, row))

    rows_with_index.sort(
        key=lambda item: (
            item[1] is None,
            0.0 if item[1] is None else item[1],
            item[0],
        )
    )
    return [entry[2] for entry in rows_with_index]
