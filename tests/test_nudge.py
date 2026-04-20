"""Tests for the Memory and Skill Nudge System (hi_agent.context.nudge)."""

from __future__ import annotations

from hi_agent.context.nudge import (
    ActionDetector,
    NudgeConfig,
    NudgeInjector,
    NudgeState,
    NudgeTrigger,
    NudgeType,
)

# ---------------------------------------------------------------------------
# NudgeState — counter helpers
# ---------------------------------------------------------------------------


def test_nudge_state_increment_turn():
    """Turn counter increments by 1 on each call."""
    state = NudgeState()
    assert state.turns_since_memory_save == 0
    state.increment_turn()
    assert state.turns_since_memory_save == 1
    state.increment_turn()
    assert state.turns_since_memory_save == 2


def test_nudge_state_increment_iter():
    """Iteration counter increments by 1 on each call."""
    state = NudgeState()
    assert state.iters_since_skill_create == 0
    state.increment_iter()
    assert state.iters_since_skill_create == 1
    state.increment_iter()
    assert state.iters_since_skill_create == 2


def test_nudge_state_reset_memory():
    """reset_memory() resets turns_since_memory_save to 0."""
    state = NudgeState(turns_since_memory_save=7)
    state.reset_memory()
    assert state.turns_since_memory_save == 0
    # iters counter is unaffected
    state.iters_since_skill_create = 5
    state.reset_memory()
    assert state.iters_since_skill_create == 5


def test_nudge_state_reset_skill():
    """reset_skill() resets iters_since_skill_create to 0."""
    state = NudgeState(iters_since_skill_create=12)
    state.reset_skill()
    assert state.iters_since_skill_create == 0
    # turns counter is unaffected
    state.turns_since_memory_save = 8
    state.reset_skill()
    assert state.turns_since_memory_save == 8


# ---------------------------------------------------------------------------
# NudgeState — serialization round-trip
# ---------------------------------------------------------------------------


def test_nudge_state_serialization():
    """to_dict() / from_dict() produce an exact round-trip."""
    original = NudgeState(
        turns_since_memory_save=3,
        iters_since_skill_create=9,
        total_memory_nudges_sent=1,
        total_skill_nudges_sent=2,
    )
    d = original.to_dict()

    assert d["turns_since_memory_save"] == 3
    assert d["iters_since_skill_create"] == 9
    assert d["total_memory_nudges_sent"] == 1
    assert d["total_skill_nudges_sent"] == 2

    restored = NudgeState.from_dict(d)
    assert restored.turns_since_memory_save == original.turns_since_memory_save
    assert restored.iters_since_skill_create == original.iters_since_skill_create
    assert restored.total_memory_nudges_sent == original.total_memory_nudges_sent
    assert restored.total_skill_nudges_sent == original.total_skill_nudges_sent


def test_nudge_state_from_dict_missing_keys():
    """from_dict() gracefully handles missing keys (forward-compatibility)."""
    state = NudgeState.from_dict({})
    assert state.turns_since_memory_save == 0
    assert state.iters_since_skill_create == 0
    assert state.total_memory_nudges_sent == 0
    assert state.total_skill_nudges_sent == 0


# ---------------------------------------------------------------------------
# NudgeInjector — threshold checks
# ---------------------------------------------------------------------------


def test_nudge_injector_no_trigger_below_interval():
    """No nudge is returned when both counters are below their intervals."""
    config = NudgeConfig(memory_nudge_interval=10, skill_nudge_interval=15)
    injector = NudgeInjector(config)
    state = NudgeState(turns_since_memory_save=5, iters_since_skill_create=7)

    triggers = injector.check(state)

    assert triggers == []


def test_nudge_injector_triggers_memory_nudge():
    """Memory nudge fires when turns_since_memory_save >= memory_nudge_interval."""
    config = NudgeConfig(memory_nudge_interval=10, skill_nudge_interval=15)
    injector = NudgeInjector(config)
    state = NudgeState(turns_since_memory_save=10, iters_since_skill_create=3)

    triggers = injector.check(state)

    assert len(triggers) == 1
    assert triggers[0].nudge_type == NudgeType.MEMORY
    assert state.total_memory_nudges_sent == 1


def test_nudge_injector_triggers_skill_nudge():
    """Skill nudge fires when iters_since_skill_create >= skill_nudge_interval."""
    config = NudgeConfig(memory_nudge_interval=10, skill_nudge_interval=15)
    injector = NudgeInjector(config)
    state = NudgeState(turns_since_memory_save=3, iters_since_skill_create=15)

    triggers = injector.check(state)

    assert len(triggers) == 1
    assert triggers[0].nudge_type == NudgeType.SKILL
    assert state.total_skill_nudges_sent == 1


def test_nudge_injector_triggers_both_nudges():
    """Both nudges fire when both counters exceed their respective intervals."""
    config = NudgeConfig(memory_nudge_interval=10, skill_nudge_interval=15)
    injector = NudgeInjector(config)
    state = NudgeState(turns_since_memory_save=12, iters_since_skill_create=20)

    triggers = injector.check(state)

    nudge_types = {t.nudge_type for t in triggers}
    assert NudgeType.MEMORY in nudge_types
    assert NudgeType.SKILL in nudge_types
    assert state.total_memory_nudges_sent == 1
    assert state.total_skill_nudges_sent == 1


def test_nudge_injector_disabled():
    """When config.enabled is False, no nudges are produced regardless of counters."""
    config = NudgeConfig(
        memory_nudge_interval=5,
        skill_nudge_interval=5,
        enabled=False,
    )
    injector = NudgeInjector(config)
    state = NudgeState(turns_since_memory_save=100, iters_since_skill_create=100)

    triggers = injector.check(state)

    assert triggers == []
    assert state.total_memory_nudges_sent == 0
    assert state.total_skill_nudges_sent == 0


# ---------------------------------------------------------------------------
# NudgeInjector — system block format
# ---------------------------------------------------------------------------


def test_nudge_injector_to_system_block():
    """to_system_block() returns a dict with role='system' and correct prefix."""
    config = NudgeConfig()
    injector = NudgeInjector(config)
    state = NudgeState(turns_since_memory_save=10, iters_since_skill_create=0)
    triggers = injector.check(state)

    assert len(triggers) == 1
    block = injector.to_system_block(triggers[0])

    assert block["role"] == "system"
    assert block["content"].startswith("[NUDGE:memory]")


def test_nudge_injector_skill_system_block_prefix():
    """to_system_block() for a skill nudge uses the correct prefix."""
    config = NudgeConfig(skill_nudge_interval=5)
    injector = NudgeInjector(config)
    state = NudgeState(iters_since_skill_create=5)
    triggers = injector.check(state)

    skill_triggers = [t for t in triggers if t.nudge_type == NudgeType.SKILL]
    assert skill_triggers, "Expected at least one skill nudge trigger"
    block = injector.to_system_block(skill_triggers[0])

    assert block["role"] == "system"
    assert block["content"].startswith("[NUDGE:skill]")


# ---------------------------------------------------------------------------
# NudgeInjector — message formatting
# ---------------------------------------------------------------------------


def test_format_message_interpolation_memory():
    """Memory nudge message replaces {turns} with the actual turn count."""
    config = NudgeConfig(memory_nudge_interval=10)
    injector = NudgeInjector(config)
    trigger = NudgeTrigger(
        nudge_type=NudgeType.MEMORY,
        message="",
        turns_elapsed=10,
        iters_elapsed=0,
    )
    msg = injector.format_message(trigger)

    assert "10" in msg


def test_format_message_interpolation_skill():
    """Skill nudge message replaces {iterations} with the actual iteration count."""
    config = NudgeConfig(skill_nudge_interval=15)
    injector = NudgeInjector(config)
    trigger = NudgeTrigger(
        nudge_type=NudgeType.SKILL,
        message="",
        turns_elapsed=0,
        iters_elapsed=15,
    )
    msg = injector.format_message(trigger)

    assert "15" in msg


def test_format_message_custom_template():
    """Custom message templates are used when provided, with placeholder substitution."""
    config = NudgeConfig(
        memory_nudge_message="已 {turns} 轮未保存, 请保存!",
    )
    injector = NudgeInjector(config)
    trigger = NudgeTrigger(
        nudge_type=NudgeType.MEMORY,
        message="",
        turns_elapsed=7,
        iters_elapsed=0,
    )
    msg = injector.format_message(trigger)

    assert msg == "已 7 轮未保存, 请保存!"


# ---------------------------------------------------------------------------
# ActionDetector — tool_calls-based detection
# ---------------------------------------------------------------------------


def test_action_detector_memory_save():
    """detect_memory_save() returns True when a tool call name contains 'memory'."""
    tool_calls = [{"name": "save_memory", "arguments": {}}]
    assert ActionDetector.detect_memory_save(tool_calls) is True


def test_action_detector_memory_save_via_save_keyword():
    """detect_memory_save() matches tool names that contain 'save' only."""
    tool_calls = [{"name": "save_user_preference", "arguments": {}}]
    assert ActionDetector.detect_memory_save(tool_calls) is True


def test_action_detector_skill_create():
    """detect_skill_create() returns True when a tool call name contains 'skill'."""
    tool_calls = [{"name": "create_skill", "arguments": {}}]
    assert ActionDetector.detect_skill_create(tool_calls) is True


def test_action_detector_skill_create_via_skill_keyword():
    """detect_skill_create() matches tool names that contain 'skill' only."""
    tool_calls = [{"name": "register_skill", "arguments": {}}]
    assert ActionDetector.detect_skill_create(tool_calls) is True


def test_action_detector_false_positive_prevention():
    """Unrelated tool names do not trigger memory-save or skill-create detection."""
    tool_calls = [
        {"name": "web_search", "arguments": {}},
        {"name": "read_file", "arguments": {}},
        {"name": "execute_code", "arguments": {}},
    ]
    assert ActionDetector.detect_memory_save(tool_calls) is False
    assert ActionDetector.detect_skill_create(tool_calls) is False


def test_action_detector_empty_tool_calls():
    """Empty tool_calls list returns False for both detectors."""
    assert ActionDetector.detect_memory_save([]) is False
    assert ActionDetector.detect_skill_create([]) is False


# ---------------------------------------------------------------------------
# ActionDetector — text-based detection
# ---------------------------------------------------------------------------


def test_action_detector_detect_from_text_memory():
    """detect_from_text() identifies memory-save intent from Chinese keywords."""
    memory_saved, skill_created = ActionDetector.detect_from_text("保存记忆完成")
    assert memory_saved is True
    assert skill_created is False


def test_action_detector_detect_from_text_skill():
    """detect_from_text() identifies skill-create intent from Chinese keywords."""
    memory_saved, skill_created = ActionDetector.detect_from_text("已经创建技能成功")
    assert memory_saved is False
    assert skill_created is True


def test_action_detector_detect_from_text_neither():
    """detect_from_text() returns (False, False) for unrelated text."""
    memory_saved, skill_created = ActionDetector.detect_from_text(
        "The search returned no relevant results."
    )
    assert memory_saved is False
    assert skill_created is False


def test_action_detector_detect_from_text_both():
    """detect_from_text() detects both intents when both keywords appear."""
    text = "save_memory called; create_skill registered pattern XYZ"
    memory_saved, skill_created = ActionDetector.detect_from_text(text)
    assert memory_saved is True
    assert skill_created is True
