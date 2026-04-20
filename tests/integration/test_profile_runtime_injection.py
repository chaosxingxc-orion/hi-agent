"""Integration tests for profile_id runtime injection.

Covers:
- TaskContract accepts profile_id
- CLI builds correct contract with --profile-id
- POST /runs passes profile_id through
- SystemBuilder resolves profile and applies it
"""

from __future__ import annotations

from hi_agent.contracts.requests import StartRunRequest
from hi_agent.contracts.task import TaskContract


class TestProfileIdOnContracts:
    def test_task_contract_accepts_profile_id(self):
        c = TaskContract(task_id="t1", goal="test", profile_id="rnd_agent")
        assert c.profile_id == "rnd_agent"

    def test_task_contract_profile_id_defaults_none(self):
        c = TaskContract(task_id="t1", goal="test")
        assert c.profile_id is None

    def test_start_run_request_accepts_profile_id(self):
        r = StartRunRequest(task_contract={}, profile_id="my_profile")
        assert r.profile_id == "my_profile"

    def test_start_run_request_profile_id_defaults_none(self):
        r = StartRunRequest(task_contract={})
        assert r.profile_id is None


class TestCLIProfileId:
    def test_cli_parser_has_profile_id(self):
        from hi_agent.cli import build_parser

        parser = build_parser()
        # Parse a minimal run command with --profile-id
        args = parser.parse_args(["run", "--goal", "test goal", "--profile-id", "my_profile"])
        assert args.profile_id == "my_profile"

    def test_cli_parser_profile_id_defaults_none(self):
        from hi_agent.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "--goal", "test goal"])
        assert args.profile_id is None


class TestProfileRuntimeResolver:
    def test_resolve_none_returns_none(self):
        from hi_agent.profiles.registry import ProfileRegistry
        from hi_agent.runtime.profile_runtime import ProfileRuntimeResolver

        resolver = ProfileRuntimeResolver(ProfileRegistry())
        assert resolver.resolve(None) is None

    def test_resolve_unknown_id_returns_none(self):
        from hi_agent.profiles.registry import ProfileRegistry
        from hi_agent.runtime.profile_runtime import ProfileRuntimeResolver

        resolver = ProfileRuntimeResolver(ProfileRegistry())
        assert resolver.resolve("nonexistent") is None

    def test_resolve_known_profile(self):
        from hi_agent.profiles.contracts import ProfileSpec
        from hi_agent.profiles.registry import ProfileRegistry
        from hi_agent.runtime.profile_runtime import ProfileRuntimeResolver

        reg = ProfileRegistry()
        reg.register(
            ProfileSpec(
                profile_id="test",
                display_name="Test Profile",
                stage_actions={"s1": "action_a", "s2": "action_b"},
            )
        )
        resolver = ProfileRuntimeResolver(reg)
        resolved = resolver.resolve("test")
        assert resolved is not None
        assert resolved.profile_id == "test"
        assert resolved.stage_actions == {"s1": "action_a", "s2": "action_b"}

    def test_resolved_profile_has_custom_actions(self):
        from hi_agent.profiles.contracts import ProfileSpec
        from hi_agent.profiles.registry import ProfileRegistry
        from hi_agent.runtime.profile_runtime import ProfileRuntimeResolver

        reg = ProfileRegistry()
        reg.register(
            ProfileSpec(
                profile_id="p1",
                display_name="P1",
                stage_actions={"a": "cap_a"},
            )
        )
        resolved = ProfileRuntimeResolver(reg).resolve("p1")
        assert resolved.has_custom_actions is True

    def test_resolved_profile_no_custom_graph_by_default(self):
        from hi_agent.profiles.contracts import ProfileSpec
        from hi_agent.profiles.registry import ProfileRegistry
        from hi_agent.runtime.profile_runtime import ProfileRuntimeResolver

        reg = ProfileRegistry()
        reg.register(ProfileSpec(profile_id="p1", display_name="P1"))
        resolved = ProfileRuntimeResolver(reg).resolve("p1")
        assert resolved.has_custom_graph is False
        assert resolved.stage_graph is None

    def test_resolved_profile_stage_graph_from_factory(self):
        from hi_agent.profiles.contracts import ProfileSpec
        from hi_agent.profiles.registry import ProfileRegistry
        from hi_agent.runtime.profile_runtime import ProfileRuntimeResolver
        from hi_agent.trajectory.stage_graph import StageGraph

        def _factory():
            g = StageGraph()
            g.add_edge("s1", "s2")
            return g

        reg = ProfileRegistry()
        reg.register(
            ProfileSpec(
                profile_id="p2",
                display_name="P2",
                stage_graph_factory=_factory,
            )
        )
        resolved = ProfileRuntimeResolver(reg).resolve("p2")
        assert resolved.has_custom_graph is True
        assert resolved.stage_graph is not None

    def test_resolved_profile_evaluator_from_factory(self):
        from hi_agent.evaluation.contracts import DefaultEvaluator
        from hi_agent.profiles.contracts import ProfileSpec
        from hi_agent.profiles.registry import ProfileRegistry
        from hi_agent.runtime.profile_runtime import ProfileRuntimeResolver

        reg = ProfileRegistry()
        reg.register(
            ProfileSpec(
                profile_id="p3",
                display_name="P3",
                evaluator_factory=lambda: DefaultEvaluator(threshold=0.8),
            )
        )
        resolved = ProfileRuntimeResolver(reg).resolve("p3")
        assert resolved.has_evaluator is True
        assert resolved.evaluator is not None


class TestSystemBuilderProfileRegistry:
    def test_builder_has_profile_registry(self):
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder()
        reg = builder.build_profile_registry()
        assert reg is not None

    def test_builder_resolve_none_profile(self):
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder()
        resolved = builder._resolve_profile(None)
        assert resolved is None

    def test_builder_resolve_registered_profile(self):
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.profiles.contracts import ProfileSpec

        builder = SystemBuilder()
        reg = builder.build_profile_registry()
        reg.register(
            ProfileSpec(
                profile_id="test_profile",
                display_name="Test",
                stage_actions={"s1": "cap_a"},
            )
        )
        resolved = builder._resolve_profile("test_profile")
        assert resolved is not None
        assert resolved.stage_actions == {"s1": "cap_a"}
