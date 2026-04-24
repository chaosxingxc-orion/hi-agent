"""Tests for GraphFactory auto_select."""

from __future__ import annotations

from hi_agent.task_mgmt.graph_factory import ComplexityScore, GraphFactory


class TestGraphFactoryAutoSelect:
    """GraphFactory.auto_select() template selection tests."""

    def test_simple_goal_selects_simple(self):
        factory = GraphFactory()
        template, graph = factory.auto_select("Fix typo", task_family="simple")
        assert template == "simple"
        # Simple has 3 nodes: S1, S3, S5
        assert graph.get_node("S1") is not None
        assert graph.get_node("S3") is not None
        assert graph.get_node("S5") is not None

    def test_default_selects_standard(self):
        factory = GraphFactory()
        template, graph = factory.auto_select(
            "Produce a comprehensive quarterly revenue report with detailed charts"
        )
        assert template == "standard"
        # Standard has 5 nodes: S1-S5
        for sid in ["S1", "S2", "S3", "S4", "S5"]:
            assert graph.get_node(sid) is not None

    def test_compare_selects_parallel_gather(self):
        factory = GraphFactory()
        template, graph = factory.auto_select("Compare the three pricing options side by side")
        assert template == "parallel_gather"
        assert graph.get_node("S2-a") is not None

    def test_explore_selects_speculative(self):
        factory = GraphFactory()
        template, graph = factory.auto_select(
            "Explore alternative approaches to the caching problem"
        )
        assert template == "speculative"
        assert graph.get_node("S3-v1") is not None
        assert graph.get_node("S3-v2") is not None

    def test_hints_override_speculative(self):
        factory = GraphFactory()
        template, _ = factory.auto_select("Simple task", hints={"speculative": True})
        assert template == "speculative"

    def test_hints_override_parallel(self):
        factory = GraphFactory()
        template, _ = factory.auto_select("Simple task", hints={"parallel": True})
        assert template == "parallel_gather"

    def test_long_goal_defaults_to_standard(self):
        factory = GraphFactory()
        long_goal = "Please analyze this complex dataset " * 5
        template, _ = factory.auto_select(long_goal)
        assert template == "standard"

    def test_build_with_explicit_complexity(self):
        factory = GraphFactory()
        score = ComplexityScore(score=0.1)
        graph = factory.build(None, score)
        # Low score -> simple
        assert graph.get_node("S1") is not None
        assert graph.get_node("S3") is not None

    def test_build_parallel_gather_explicit(self):
        factory = GraphFactory()
        score = ComplexityScore(score=0.8, needs_parallel_gather=True)
        graph = factory.build(None, score)
        assert graph.get_node("S2-a") is not None
