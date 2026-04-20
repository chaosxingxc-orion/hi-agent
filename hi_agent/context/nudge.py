"""Memory and Skill Nudge System for hi-agent.

Periodically injects guidance messages into the agent's task view
to encourage memory saving and skill creation. This drives the agent
to continuously accumulate reusable knowledge (P1: continuous evolution).

Inspired by Hermes Agent's nudge mechanism.

Design:
- NudgeState tracks turn/iteration counters (persisted with RunContext)
- NudgeInjector checks counters and generates nudge messages
- Nudge messages are injected as isolated system blocks (don't pollute history)
- Counters reset when agent performs the target action (save memory / create skill)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

# ---------------------------------------------------------------------------
# NudgeType
# ---------------------------------------------------------------------------


class NudgeType(StrEnum):
    """Type of nudge to inject."""

    MEMORY = "memory"  # 提醒保存记忆
    SKILL = "skill"  # 提醒创建技能


# ---------------------------------------------------------------------------
# NudgeConfig
# ---------------------------------------------------------------------------


@dataclass
class NudgeConfig:
    """Configuration for the nudge system.

    Controls when nudges are triggered and what messages are sent.
    Custom messages can be provided; if left empty the default templates
    (with ``{turns}`` / ``{iterations}`` placeholders) are used.
    """

    DEFAULT_MEMORY_MESSAGE: ClassVar[str] = (
        "你已经执行了 {turns} 轮对话，但尚未保存记忆。"
        "请考虑使用记忆工具保存用户偏好、重要发现或关键上下文，"
        "以便在未来对话中复用。"
    )
    DEFAULT_SKILL_MESSAGE: ClassVar[str] = (
        "你已经执行了 {iterations} 次工具调用，但尚未创建技能。"
        "如果你发现了可复用的解决模式，请考虑将其保存为技能，"
        "以便在未来任务中直接调用，降低成本。"
    )

    memory_nudge_interval: int = 10  # 每 N 轮触发记忆提醒
    skill_nudge_interval: int = 15  # 每 N 次工具迭代触发技能提醒
    enabled: bool = True
    memory_nudge_message: str = ""  # 空时使用默认消息
    skill_nudge_message: str = ""  # 空时使用默认消息


# ---------------------------------------------------------------------------
# NudgeState
# ---------------------------------------------------------------------------


@dataclass
class NudgeState:
    """Per-run mutable nudge counters.

    Intended to be serialized alongside RunContext so counters survive
    checkpoint/resume cycles.
    """

    turns_since_memory_save: int = 0
    iters_since_skill_create: int = 0
    total_memory_nudges_sent: int = 0
    total_skill_nudges_sent: int = 0

    def increment_turn(self) -> None:
        """Increment the turn counter (called once per conversation turn)."""
        self.turns_since_memory_save += 1

    def increment_iter(self) -> None:
        """Increment the iteration counter (called once per tool invocation)."""
        self.iters_since_skill_create += 1

    def reset_memory(self) -> None:
        """Reset the memory-save counter when a memory-save action is detected."""
        self.turns_since_memory_save = 0

    def reset_skill(self) -> None:
        """Reset the skill-create counter when a skill-create action is detected."""
        self.iters_since_skill_create = 0

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict for RunContext persistence."""
        return {
            "turns_since_memory_save": self.turns_since_memory_save,
            "iters_since_skill_create": self.iters_since_skill_create,
            "total_memory_nudges_sent": self.total_memory_nudges_sent,
            "total_skill_nudges_sent": self.total_skill_nudges_sent,
        }

    @classmethod
    def from_dict(cls, d: dict) -> NudgeState:
        """Deserialize from a dict (supports missing keys for forward-compat)."""
        return cls(
            turns_since_memory_save=d.get("turns_since_memory_save", 0),
            iters_since_skill_create=d.get("iters_since_skill_create", 0),
            total_memory_nudges_sent=d.get("total_memory_nudges_sent", 0),
            total_skill_nudges_sent=d.get("total_skill_nudges_sent", 0),
        )


# ---------------------------------------------------------------------------
# NudgeTrigger
# ---------------------------------------------------------------------------


@dataclass
class NudgeTrigger:
    """Describes a single nudge that should be injected into the task view."""

    nudge_type: NudgeType
    message: str
    turns_elapsed: int
    iters_elapsed: int


# ---------------------------------------------------------------------------
# NudgeInjector
# ---------------------------------------------------------------------------


class NudgeInjector:
    """Checks NudgeState against NudgeConfig and produces NudgeTriggers.

    Usage::

        config = NudgeConfig(memory_nudge_interval=10, skill_nudge_interval=15)
        injector = NudgeInjector(config)

        # After each turn / tool call:
        state.increment_turn()
        triggers = injector.check(state)
        for trigger in triggers:
            block = injector.to_system_block(trigger)
            # inject block into the task view messages list
    """

    def __init__(self, config: NudgeConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, state: NudgeState) -> list[NudgeTrigger]:
        """Return a list of NudgeTriggers that should be injected now.

        Increments the internal sent-counters on the state for any trigger
        that is returned, so callers do not need to do that manually.
        """
        if not self._config.enabled:
            return []

        triggers: list[NudgeTrigger] = []

        # --- memory nudge ---
        if state.turns_since_memory_save >= self._config.memory_nudge_interval:
            trigger = NudgeTrigger(
                nudge_type=NudgeType.MEMORY,
                message=self.format_message(
                    NudgeTrigger(
                        nudge_type=NudgeType.MEMORY,
                        message="",
                        turns_elapsed=state.turns_since_memory_save,
                        iters_elapsed=state.iters_since_skill_create,
                    )
                ),
                turns_elapsed=state.turns_since_memory_save,
                iters_elapsed=state.iters_since_skill_create,
            )
            state.total_memory_nudges_sent += 1
            triggers.append(trigger)

        # --- skill nudge ---
        if state.iters_since_skill_create >= self._config.skill_nudge_interval:
            trigger = NudgeTrigger(
                nudge_type=NudgeType.SKILL,
                message=self.format_message(
                    NudgeTrigger(
                        nudge_type=NudgeType.SKILL,
                        message="",
                        turns_elapsed=state.turns_since_memory_save,
                        iters_elapsed=state.iters_since_skill_create,
                    )
                ),
                turns_elapsed=state.turns_since_memory_save,
                iters_elapsed=state.iters_since_skill_create,
            )
            state.total_skill_nudges_sent += 1
            triggers.append(trigger)

        return triggers

    def format_message(self, trigger: NudgeTrigger) -> str:
        """Format the nudge message, substituting ``{turns}`` / ``{iterations}``."""
        if trigger.nudge_type == NudgeType.MEMORY:
            template = self._config.memory_nudge_message or NudgeConfig.DEFAULT_MEMORY_MESSAGE
            return template.format(
                turns=trigger.turns_elapsed,
                iterations=trigger.iters_elapsed,
            )
        else:  # NudgeType.SKILL
            template = self._config.skill_nudge_message or NudgeConfig.DEFAULT_SKILL_MESSAGE
            return template.format(
                turns=trigger.turns_elapsed,
                iterations=trigger.iters_elapsed,
            )

    def to_system_block(self, trigger: NudgeTrigger) -> dict:
        """Convert a NudgeTrigger into a TaskView-injectable message dict.

        The returned dict uses ``role="system"`` so it is isolated from the
        conversation history and does not pollute the agent's message list.
        """
        message = trigger.message or self.format_message(trigger)
        return {
            "role": "system",
            "content": f"[NUDGE:{trigger.nudge_type}] {message}",
        }


# ---------------------------------------------------------------------------
# ActionDetector
# ---------------------------------------------------------------------------


class ActionDetector:
    """Static utility class that detects memory-save and skill-create actions.

    Used to decide when to reset NudgeState counters after the agent has
    already taken the desired action.
    """

    # Keywords used for text-based detection
    _MEMORY_SAVE_KEYWORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "save_memory",
            "memory_save",
            "add_memory",
            "store_memory",
            "保存记忆",
            "存储记忆",
            "记忆已保存",
        }
    )
    _SKILL_CREATE_KEYWORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "create_skill",
            "save_skill",
            "add_skill",
            "register_skill",
            "创建技能",
            "保存技能",
            "技能已创建",
        }
    )

    @staticmethod
    def detect_memory_save(tool_calls: list[dict]) -> bool:
        """Return True if any tool call looks like a memory-save action.

        Matches on ``name`` containing "memory" **or** "save" (case-insensitive).
        """
        for call in tool_calls:
            name: str = call.get("name", "").lower()
            if "memory" in name or "save" in name:
                return True
        return False

    @staticmethod
    def detect_skill_create(tool_calls: list[dict]) -> bool:
        """Return True if any tool call looks like a skill-create action.

        Matches on ``name`` containing "skill" **or** "create_skill"
        (case-insensitive).
        """
        for call in tool_calls:
            name: str = call.get("name", "").lower()
            if "skill" in name or "create_skill" in name:
                return True
        return False

    @staticmethod
    def detect_from_text(text: str) -> tuple[bool, bool]:
        """Detect memory-save and skill-create intent from free-form text.

        Uses simple keyword matching.

        Returns:
            (memory_saved, skill_created) — each True when the respective
            intent is detected.
        """
        lower = text.lower()

        memory_saved = any(kw in lower for kw in ActionDetector._MEMORY_SAVE_KEYWORDS)
        skill_created = any(kw in lower for kw in ActionDetector._SKILL_CREATE_KEYWORDS)

        return memory_saved, skill_created
