"""Posture-matrix coverage for trajectory contracts (AX-B B5).

Covers:
  hi_agent/contracts/trajectory.py — TrajectoryNode, NodeType, NodeState

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture


# ---------------------------------------------------------------------------
# TrajectoryNode
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_trajectory_node_instantiates_under_posture(monkeypatch, posture_name):
    """TrajectoryNode must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.trajectory import NodeType, TrajectoryNode

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    node = TrajectoryNode(
        node_id="n1",
        node_type=NodeType.DECISION,
        stage_id="s1",
        branch_id="b1",
    )
    assert node.node_id == "n1"
    assert node.node_type == NodeType.DECISION
    assert node.stage_id == "s1"
    assert node.branch_id == "b1"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_trajectory_node_requires_required_fields(monkeypatch, posture_name):
    """TrajectoryNode without required fields raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.trajectory import TrajectoryNode

    with pytest.raises(TypeError):
        TrajectoryNode()  # missing node_id, node_type, stage_id, branch_id


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_trajectory_node_state_defaults_open(monkeypatch, posture_name):
    """TrajectoryNode.state defaults to OPEN under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.trajectory import NodeState, NodeType, TrajectoryNode

    node = TrajectoryNode(
        node_id="n1",
        node_type=NodeType.ACTION,
        stage_id="s1",
        branch_id="b1",
    )
    assert node.state == NodeState.OPEN


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_node_type_enum_values_under_posture(monkeypatch, posture_name):
    """NodeType enum values are importable and correct under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.trajectory import NodeType

    assert NodeType.DECISION == "decision"
    assert NodeType.ACTION == "action"
    assert NodeType.EVIDENCE == "evidence"
    assert NodeType.SYNTHESIS == "synthesis"
    assert NodeType.CHECKPOINT == "checkpoint"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_node_state_enum_values_under_posture(monkeypatch, posture_name):
    """NodeState enum values are importable and correct under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.trajectory import NodeState

    assert NodeState.OPEN == "open"
    assert NodeState.EXPANDED == "expanded"
    assert NodeState.PRUNED == "pruned"
    assert NodeState.SUCCEEDED == "succeeded"
    assert NodeState.FAILED == "failed"
