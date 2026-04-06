"""Spike 2: verify deterministic identity generation."""

from hi_agent.contracts import deterministic_id


def test_deterministic_id_same_input_same_output() -> None:
    """Same input must always map to the same deterministic ID."""
    first_id = deterministic_id("run1", "s1", "b1", "search_arxiv_v1", "0")
    second_id = deterministic_id("run1", "s1", "b1", "search_arxiv_v1", "0")

    assert first_id == second_id


def test_deterministic_id_different_input_different_output() -> None:
    """Different inputs should not collide in common cases."""
    first_id = deterministic_id("run1", "s1", "b1", "search_arxiv_v1", "0")
    second_id = deterministic_id("run1", "s1", "b1", "search_arxiv_v1", "1")

    assert first_id != second_id


def test_task_view_id_includes_policy_version() -> None:
    """Changing policy version should alter task_view_id."""
    first_id = deterministic_id("run1", "s1", "b1", "0", "evidence_hash_1", "policy_v1")
    second_id = deterministic_id("run1", "s1", "b1", "0", "evidence_hash_1", "policy_v2")

    assert first_id != second_id


def test_task_view_id_same_evidence_same_policy() -> None:
    """Same evidence and policy should keep task_view_id stable."""
    first_id = deterministic_id("run1", "s1", "b1", "0", "evidence_hash_1", "policy_v1")
    second_id = deterministic_id("run1", "s1", "b1", "0", "evidence_hash_1", "policy_v1")

    assert first_id == second_id
