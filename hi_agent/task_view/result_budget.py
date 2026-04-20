"""Tool Result Budget Control for hi-agent.

Prevents large tool results from exploding the context window.
Results exceeding the per-result token limit are replaced with
a content hash + size summary. A cumulative budget tracks total
tool result tokens across the conversation.

Inspired by Claude Code's tool result budget mechanism.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class ToolResultBudgetConfig:
    """Configuration for tool result budget control.

    Attributes:
        max_single_result_chars: Maximum characters for a single tool result.
            Results exceeding this limit are replaced with a placeholder.
            Default 32_000 ≈ 8 k tokens (4 chars/token heuristic).
        max_cumulative_chars: Maximum total characters of tool results
            accumulated across all turns in a conversation.  Once this is
            exceeded every subsequent result is truncated regardless of its
            individual size.
        truncation_marker: Short token used to mark a truncated field.
        show_hash: Include the SHA-256 content hash in the placeholder.
        show_original_size: Include the original character count in the
            placeholder.
    """

    max_single_result_chars: int = 32_000
    max_cumulative_chars: int = 128_000
    truncation_marker: str = "[TRUNCATED]"
    show_hash: bool = True
    show_original_size: bool = True


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass
class TruncatedResult:
    """Metadata about a tool result that was truncated.

    Attributes:
        original_chars: Character count of the original content.
        content_hash: First 16 hex characters of the SHA-256 digest.
        tool_name: Name of the tool that produced the result.
        marker: The truncation marker string taken from the config.
    """

    original_chars: int
    content_hash: str
    tool_name: str
    marker: str

    def to_placeholder(self) -> str:
        """Return a human-readable placeholder string for the truncated result.

        Format:
            ``[TRUNCATED: tool=<name>, size=<N>chars, hash=<hex>]``
        """
        return (
            f"[TRUNCATED: tool={self.tool_name}, "
            f"size={self.original_chars}chars, "
            f"hash={self.content_hash}]"
        )


# ---------------------------------------------------------------------------
# Mutable budget state (serialisable for RunContext)
# ---------------------------------------------------------------------------


@dataclass
class ToolResultBudgetState:
    """Mutable per-run state for the tool result budget.

    This dataclass is intentionally kept flat so that it can be trivially
    serialised to / deserialised from a JSON-compatible dict and stored inside
    ``RunContext.metadata``.

    Attributes:
        cumulative_chars_used: Total characters consumed by tool results so
            far in this run.
        truncation_count: Number of results that have been truncated.
    """

    cumulative_chars_used: int = 0
    truncation_count: int = 0

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def remaining_chars(self, max_cumulative: int) -> int:
        """Return how many characters remain in the cumulative budget.

        Returns 0 if the budget is already exhausted.
        """
        remaining = max_cumulative - self.cumulative_chars_used
        return max(0, remaining)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def record_result(self, chars: int) -> None:
        """Accumulate *chars* into the cumulative usage counter."""
        self.cumulative_chars_used += chars

    def record_truncation(self) -> None:
        """Increment the truncation counter by one."""
        self.truncation_count += 1

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise state to a JSON-compatible dict."""
        return {
            "cumulative_chars_used": self.cumulative_chars_used,
            "truncation_count": self.truncation_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolResultBudgetState:
        """Deserialise state from a dict produced by :meth:`to_dict`."""
        return cls(
            cumulative_chars_used=data.get("cumulative_chars_used", 0),
            truncation_count=data.get("truncation_count", 0),
        )


# ---------------------------------------------------------------------------
# Core budget controller
# ---------------------------------------------------------------------------


class ToolResultBudget:
    """Controls the size of tool results before they enter the TaskView.

    Each call to :meth:`process` checks whether the result fits within both
    the single-result limit and the remaining cumulative budget.  Results that
    exceed either limit are replaced by a compact placeholder string that
    includes a content hash so the model can still reason about identity.

    Args:
        config: Static configuration limits.
        state: Mutable run-level state (shared across turns).
    """

    def __init__(
        self,
        config: ToolResultBudgetConfig,
        state: ToolResultBudgetState,
    ) -> None:
        self._config = config
        self._state = state

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, tool_name: str, result_content: str) -> str:
        """Apply the budget policy to a single tool result.

        If the result fits within both the per-result limit and the remaining
        cumulative budget the original string is returned unchanged and the
        state is updated.  Otherwise a :class:`TruncatedResult` placeholder
        is returned and the truncation counter is incremented.

        Args:
            tool_name: Name of the tool that produced the result.
            result_content: Raw string content of the tool result.

        Returns:
            Either the original *result_content* or a compact placeholder.
        """
        char_count = len(result_content)

        within_single = char_count <= self._config.max_single_result_chars
        within_cumulative = char_count <= self._state.remaining_chars(
            self._config.max_cumulative_chars
        )

        if within_single and within_cumulative:
            self._state.record_result(char_count)
            return result_content

        # --- truncation path ---
        content_hash = _sha256_prefix(result_content)
        truncated = TruncatedResult(
            original_chars=char_count,
            content_hash=content_hash,
            tool_name=tool_name,
            marker=self._config.truncation_marker,
        )
        # Record the placeholder size (not the original) for budget tracking
        placeholder = truncated.to_placeholder()
        self._state.record_result(len(placeholder))
        self._state.record_truncation()
        return placeholder

    def process_message_results(self, messages: list[dict]) -> list[dict]:
        """Apply the budget policy to all tool-result messages in a list.

        Only messages whose ``role`` is ``"tool"`` are processed.  Other
        messages are copied verbatim.  The original list and its elements are
        never mutated; a deep copy is returned.

        Args:
            messages: A list of message dicts in the OpenAI / Anthropic
                conversation format.  Each dict is expected to contain at
                least a ``"role"`` key.  Tool messages should also contain a
                ``"content"`` key (str or list of content blocks).

        Returns:
            A new list of message dicts with oversized tool results replaced.
        """
        result: list[dict] = []
        for msg in messages:
            msg_copy = copy.deepcopy(msg)
            if msg_copy.get("role") == "tool":
                tool_name = msg_copy.get("name", msg_copy.get("tool_name", "unknown"))
                content = msg_copy.get("content", "")
                if isinstance(content, str):
                    msg_copy["content"] = self.process(tool_name, content)
                elif isinstance(content, list):
                    processed_blocks: list[Any] = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            new_block = dict(block)
                            new_block["text"] = self.process(tool_name, block.get("text", ""))
                            processed_blocks.append(new_block)
                        else:
                            processed_blocks.append(block)
                    msg_copy["content"] = processed_blocks
            result.append(msg_copy)
        return result

    def get_state(self) -> ToolResultBudgetState:
        """Return the current mutable budget state."""
        return self._state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def estimate_chars(content: str | list | dict) -> int:
    """Estimate the character footprint of *content*.

    This is a lightweight heuristic — it does *not* tokenise.

    * ``str``  → ``len(content)``
    * ``list`` → sum of recursive estimates for each element
    * ``dict`` → ``len(str(content))`` (simplified)
    * anything else → ``len(str(content))``

    Args:
        content: Arbitrary content to estimate.

    Returns:
        Estimated character count (always ≥ 0).
    """
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(estimate_chars(item) for item in content)
    if isinstance(content, dict):
        return len(str(content))
    return len(str(content))


def _sha256_prefix(text: str, length: int = 16) -> str:
    """Return the first *length* hex characters of the SHA-256 digest of *text*."""
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return digest[:length]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_tool_result_budget(
    config_dict: dict | None = None,
) -> ToolResultBudget:
    """Create a :class:`ToolResultBudget` from an optional configuration dict.

    The *config_dict* may contain any subset of the fields defined in
    :class:`ToolResultBudgetConfig`.  Unknown keys are silently ignored.

    Args:
        config_dict: Optional dict with configuration overrides.  Pass
            ``None`` (or omit) to use all defaults.

    Returns:
        A freshly initialised :class:`ToolResultBudget` with a zeroed state.
    """
    if config_dict is None:
        config_dict = {}

    known_fields = {
        "max_single_result_chars",
        "max_cumulative_chars",
        "truncation_marker",
        "show_hash",
        "show_original_size",
    }
    filtered = {k: v for k, v in config_dict.items() if k in known_fields}
    config = ToolResultBudgetConfig(**filtered)
    state = ToolResultBudgetState()
    return ToolResultBudget(config=config, state=state)
