"""Task view token budget helpers."""

from __future__ import annotations

from collections.abc import Callable

DEFAULT_BUDGET = 9728  # tokens

LAYER_BUDGETS: dict[str, int] = {
    "l2_index": 512,
    "l1_current_stage": 2048,
    "l1_previous_stage": 2048,
    "l3_episodic": 1024,
    "knowledge": 1024,
    "system_reserved": 512,
}

# Pluggable token counter. Replace with a real tokenizer when available.
_token_counter: Callable[[str], int] | None = None


def set_token_counter(fn: Callable[[str], int] | None) -> None:
    """Override the global token counting function.

    Pass *None* to restore the default heuristic.
    """
    global _token_counter
    _token_counter = fn


def count_tokens(text: str) -> int:
    """Estimate token count. 4 chars ~ 1 token by default.

    If a custom counter was registered via :func:`set_token_counter`, it is
    used instead.
    """
    if _token_counter is not None:
        return _token_counter(text)
    return max(1, len(text) // 4)


def enforce_budget(items: list[str], max_items: int) -> list[str]:
    """Trim list to fixed item budget while preserving order.

    This is the legacy item-count helper kept for backward compatibility.
    """
    if max_items < 0:
        raise ValueError("max_items must be non-negative")
    return items[:max_items]


def enforce_layer_budget(content: str, max_tokens: int) -> str:
    """Truncate *content* to fit within *max_tokens* budget.

    Truncation is performed on a character basis using the inverse of the
    default heuristic (4 chars per token).  If a custom counter is set the
    function iteratively trims until the budget is met.
    """
    if max_tokens <= 0:
        return ""
    current = count_tokens(content)
    if current <= max_tokens:
        return content

    # Fast path for default heuristic
    if _token_counter is None:
        max_chars = max_tokens * 4
        return content[:max_chars]

    # Iterative trim for custom counters
    low, high = 0, len(content)
    best = 0
    while low <= high:
        mid = (low + high) // 2
        if count_tokens(content[:mid]) <= max_tokens:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return content[:best]
