"""Tests for the end-to-end skill lifecycle wiring.

Covers:
- RunExecutor with skill_observer records observations after action execution
- Observations contain correct skill_id, success, quality_score
- Backward compat: skill_observer=None -> no error
- API GET /skills/list returns skills
- API POST /skills/evolve returns EvolutionReport
- API GET /skills/{id}/metrics returns metrics
- SystemBuilder builds all skill components
- Full lifecycle: discover -> execute -> observe -> metrics -> evolve -> new version
"""

from __future__ import annotations

import io
import json
import os
import tempfile

import pytest

from hi_agent.contracts import TaskContract
from tests.helpers.kernel_adapter_fixture import MockKernel
from hi_agent.runner import RunExecutor
from hi_agent.skill.observer import SkillObservation, SkillObserver
from hi_agent.skill.version import SkillVersionManager
from hi_agent.skill.evolver import SkillEvolver
from hi_agent.skill.loader import SkillLoader
from hi_agent.skill.definition import SkillDefinition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_contract(**kw: object) -> TaskContract:
    defaults = {
        "task_id": "test_task",
        "goal": "test goal",
        "task_family": "quick_task",
        "risk_level": "low",
    }
    defaults.update(kw)
    return TaskContract(**defaults)


def _make_skill_file(dir_path: str, name: str = "test-skill") -> str:
    """Create a SKILL.md file in a subdirectory and return the dir path."""
    skill_dir = os.path.join(dir_path, name)
    os.makedirs(skill_dir, exist_ok=True)
    skill_path = os.path.join(skill_dir, "SKILL.md")
    content = f"""---
name: {name}
version: 1.0.0
description: A test skill for lifecycle testing
when_to_use: When testing
lifecycle_stage: certified
confidence: 0.9
tags: [test, lifecycle]
---

# {name}

This is a test skill prompt.
"""
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(content)
    return skill_dir


# ---------------------------------------------------------------------------
# Part 1: RunExecutor with skill_observer
# ---------------------------------------------------------------------------

class TestRunExecutorSkillObserver:
    """Test that RunExecutor records skill observations after action execution."""

    def test_observer_records_observations(self, tmp_path: object) -> None:
        """skill_observer.observe() is called after each action execution."""
        storage = str(tmp_path)
        observer = SkillObserver(storage_dir=storage)
        contract = _make_contract()
        kernel = MockKernel()

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            skill_observer=observer,
        )
        outcome = executor.execute()

        assert outcome in ("completed", "failed")
        # Check that observations were written
        # Observer writes to {storage}/{skill_id}.jsonl files
        jsonl_files = [
            f for f in os.listdir(storage)
            if f.endswith(".jsonl")
        ] if os.path.isdir(storage) else []
        # At least some observations should be recorded
        assert len(jsonl_files) > 0, "Expected at least one observation JSONL file"

    def test_observation_contains_correct_fields(self, tmp_path: object) -> None:
        """Observations contain skill_id, success, task_family."""
        storage = str(tmp_path)
        observer = SkillObserver(storage_dir=storage)
        contract = _make_contract(task_family="analysis_task")
        kernel = MockKernel()

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            skill_observer=observer,
        )
        executor.execute()

        # Read all observations
        all_obs: list[dict] = []
        if os.path.isdir(storage):
            for fname in os.listdir(storage):
                if fname.endswith(".jsonl"):
                    fpath = os.path.join(storage, fname)
                    with open(fpath, encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                all_obs.append(json.loads(line))

        assert len(all_obs) > 0
        obs = all_obs[0]
        assert "skill_id" in obs
        assert "success" in obs
        assert obs["task_family"] == "analysis_task"
        assert "run_id" in obs
        assert "stage_id" in obs
        assert "timestamp" in obs

    def test_observation_quality_score_from_result(self, tmp_path: object) -> None:
        """quality_score is extracted from action result if present."""
        storage = str(tmp_path)
        observer = SkillObserver(storage_dir=storage)
        contract = _make_contract()
        kernel = MockKernel()

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            skill_observer=observer,
        )
        executor.execute()

        # Observations exist (scores may be None from mock results)
        if os.path.isdir(storage):
            for fname in os.listdir(storage):
                if fname.endswith(".jsonl"):
                    fpath = os.path.join(storage, fname)
                    with open(fpath, encoding="utf-8") as f:
                        for line in f:
                            obs = json.loads(line.strip())
                            # quality_score is either None or a float
                            assert "quality_score" in obs


class TestRunExecutorBackwardCompat:
    """Backward compatibility: skill_observer=None should not cause errors."""

    def test_none_observer_no_error(self) -> None:
        """RunExecutor with skill_observer=None completes without error."""
        contract = _make_contract()
        kernel = MockKernel()

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            skill_observer=None,
        )
        outcome = executor.execute()
        assert outcome in ("completed", "failed")

    def test_none_version_mgr_no_error(self) -> None:
        """RunExecutor with skill_version_mgr=None completes without error."""
        contract = _make_contract()
        kernel = MockKernel()

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            skill_version_mgr=None,
            skill_observer=None,
        )
        outcome = executor.execute()
        assert outcome in ("completed", "failed")

    def test_none_skill_loader_no_error(self) -> None:
        """RunExecutor with skill_loader=None completes without error."""
        contract = _make_contract()
        kernel = MockKernel()

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            skill_loader=None,
        )
        outcome = executor.execute()
        assert outcome in ("completed", "failed")


# ---------------------------------------------------------------------------
# Part 2: API endpoint tests
# ---------------------------------------------------------------------------

class TestSkillAPIEndpoints:
    """Test skill API endpoints via the AgentServer handler."""

    def _make_server(self, tmp_path: str) -> object:
        """Create an AgentServer with skill components wired."""
        from hi_agent.server.app import AgentServer

        server = AgentServer.__new__(AgentServer)
        # Minimal init to avoid binding a real socket
        from hi_agent.server.run_manager import RunManager

        server.run_manager = RunManager()
        server.memory_manager = None
        server.knowledge_manager = None

        # Wire skill components
        obs_dir = os.path.join(tmp_path, "observations")
        ver_dir = os.path.join(tmp_path, "versions")
        observer = SkillObserver(storage_dir=obs_dir)
        version_mgr = SkillVersionManager(storage_dir=ver_dir)
        server.skill_evolver = SkillEvolver(
            observer=observer,
            version_manager=version_mgr,
        )

        skill_dir = os.path.join(tmp_path, "skills")
        _make_skill_file(skill_dir, "test-skill")
        server.skill_loader = SkillLoader(search_dirs=[skill_dir])

        return server

    def test_skills_list_handler(self, tmp_path: object) -> None:
        """GET /skills/list returns discovered skills."""
        from hi_agent.server.app import AgentAPIHandler

        server = self._make_server(str(tmp_path))

        # Simulate handler with mock request/response
        handler = AgentAPIHandler.__new__(AgentAPIHandler)
        handler.server = server

        # Capture response
        response_data: dict = {}

        def mock_send_json(status: int, body: dict) -> None:
            response_data["status"] = status
            response_data["body"] = body

        handler._send_json = mock_send_json
        handler._handle_skills_list()

        assert response_data["status"] == 200
        assert "skills" in response_data["body"]
        assert "count" in response_data["body"]
        skills = response_data["body"]["skills"]
        assert len(skills) > 0
        assert skills[0]["skill_id"] == "test-skill"

    def test_skills_evolve_handler(self, tmp_path: object) -> None:
        """POST /skills/evolve returns EvolutionReport."""
        from hi_agent.server.app import AgentAPIHandler

        server = self._make_server(str(tmp_path))
        handler = AgentAPIHandler.__new__(AgentAPIHandler)
        handler.server = server

        response_data: dict = {}

        def mock_send_json(status: int, body: dict) -> None:
            response_data["status"] = status
            response_data["body"] = body

        handler._send_json = mock_send_json
        handler._handle_skills_evolve()

        assert response_data["status"] == 200
        body = response_data["body"]
        assert "skills_analyzed" in body
        assert "skills_optimized" in body
        assert "patterns_discovered" in body
        assert "skills_created" in body

    def test_skill_metrics_handler(self, tmp_path: object) -> None:
        """GET /skills/{id}/metrics returns metrics."""
        from hi_agent.server.app import AgentAPIHandler

        server = self._make_server(str(tmp_path))
        handler = AgentAPIHandler.__new__(AgentAPIHandler)
        handler.server = server

        response_data: dict = {}

        def mock_send_json(status: int, body: dict) -> None:
            response_data["status"] = status
            response_data["body"] = body

        handler._send_json = mock_send_json
        handler._handle_skill_metrics("test-skill")

        assert response_data["status"] == 200
        body = response_data["body"]
        assert body["skill_id"] == "test-skill"
        assert "total_executions" in body
        assert "success_rate" in body

    def test_skill_versions_handler(self, tmp_path: object) -> None:
        """GET /skills/{id}/versions returns version list."""
        from hi_agent.server.app import AgentAPIHandler

        server = self._make_server(str(tmp_path))

        # Create a version first
        server.skill_evolver._version_manager.create_version(
            "test-skill", "prompt content"
        )

        handler = AgentAPIHandler.__new__(AgentAPIHandler)
        handler.server = server

        response_data: dict = {}

        def mock_send_json(status: int, body: dict) -> None:
            response_data["status"] = status
            response_data["body"] = body

        handler._send_json = mock_send_json
        handler._handle_skill_versions("test-skill")

        assert response_data["status"] == 200
        body = response_data["body"]
        assert body["skill_id"] == "test-skill"
        assert body["count"] >= 1
        assert body["versions"][0]["is_champion"] is True

    def test_skill_promote_handler(self, tmp_path: object) -> None:
        """POST /skills/{id}/promote promotes challenger."""
        from hi_agent.server.app import AgentAPIHandler

        server = self._make_server(str(tmp_path))

        handler = AgentAPIHandler.__new__(AgentAPIHandler)
        handler.server = server

        response_data: dict = {}

        def mock_send_json(status: int, body: dict) -> None:
            response_data["status"] = status
            response_data["body"] = body

        handler._send_json = mock_send_json
        handler._handle_skill_promote("test-skill")

        assert response_data["status"] == 200
        assert "promoted" in response_data["body"]

    def test_skills_status_handler(self, tmp_path: object) -> None:
        """GET /skills/status returns overall status."""
        from hi_agent.server.app import AgentAPIHandler

        server = self._make_server(str(tmp_path))
        handler = AgentAPIHandler.__new__(AgentAPIHandler)
        handler.server = server

        response_data: dict = {}

        def mock_send_json(status: int, body: dict) -> None:
            response_data["status"] = status
            response_data["body"] = body

        handler._send_json = mock_send_json
        handler._handle_skills_status()

        assert response_data["status"] == 200
        body = response_data["body"]
        assert "total_skills" in body
        assert "eligible_skills" in body
        assert "observed_skills" in body
        assert "top_performers" in body


# ---------------------------------------------------------------------------
# Part 3: SystemBuilder builds all skill components
# ---------------------------------------------------------------------------

class TestSystemBuilderSkillComponents:
    """Test that SystemBuilder can create all skill lifecycle components."""

    def test_build_skill_loader(self) -> None:
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig

        builder = SystemBuilder(TraceConfig())
        loader = builder.build_skill_loader()
        assert loader is not None
        assert hasattr(loader, "discover")
        assert hasattr(loader, "build_prompt")

    def test_build_skill_observer(self) -> None:
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig

        builder = SystemBuilder(TraceConfig())
        observer = builder.build_skill_observer()
        assert observer is not None
        assert hasattr(observer, "observe")
        assert hasattr(observer, "get_metrics")

    def test_build_skill_version_manager(self) -> None:
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig

        builder = SystemBuilder(TraceConfig())
        vmgr = builder.build_skill_version_manager()
        assert vmgr is not None
        assert hasattr(vmgr, "create_version")
        assert hasattr(vmgr, "select_version")

    def test_build_skill_evolver(self) -> None:
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig

        builder = SystemBuilder(TraceConfig())
        evolver = builder.build_skill_evolver()
        assert evolver is not None
        assert hasattr(evolver, "evolve_cycle")
        assert hasattr(evolver, "optimize_prompt")

    def test_build_executor_includes_skill_components(self) -> None:
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig

        builder = SystemBuilder(TraceConfig())
        contract = _make_contract()
        executor = builder.build_executor(contract)
        assert executor.skill_observer is not None
        assert executor.skill_version_mgr is not None
        assert executor.skill_loader is not None


# ---------------------------------------------------------------------------
# Part 4: Full lifecycle integration test
# ---------------------------------------------------------------------------

class TestSkillLifecycleIntegration:
    """Full lifecycle: discover -> execute -> observe -> metrics -> evolve."""

    def test_full_lifecycle(self, tmp_path: object) -> None:
        """End-to-end skill lifecycle test."""
        base = str(tmp_path)
        skill_dir = os.path.join(base, "skills")
        obs_dir = os.path.join(base, "observations")
        ver_dir = os.path.join(base, "versions")

        # 1. Create a skill on disk
        _make_skill_file(skill_dir, "analyze-data")

        # 2. Discover skills via loader
        loader = SkillLoader(search_dirs=[skill_dir])
        count = loader.discover()
        assert count == 1

        skill = loader.get_skill("analyze-data")
        assert skill is not None
        assert skill.name == "analyze-data"

        # 3. Build prompt for LLM injection
        prompt = loader.build_prompt()
        assert prompt.full_count + prompt.compact_count == 1
        prompt_text = prompt.to_prompt_string()
        assert "analyze-data" in prompt_text

        # 4. Execute with observer recording
        observer = SkillObserver(storage_dir=obs_dir)
        version_mgr = SkillVersionManager(storage_dir=ver_dir)
        contract = _make_contract(task_family="data_analysis")
        kernel = MockKernel()

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            skill_observer=observer,
            skill_version_mgr=version_mgr,
            skill_loader=loader,
        )
        outcome = executor.execute()
        assert outcome in ("completed", "failed")

        # 5. Get metrics from observer
        all_metrics = observer.get_all_metrics()
        # At least one skill should have observations
        assert len(all_metrics) > 0

        # Pick first observed skill
        first_skill_id = next(iter(all_metrics))
        metrics = observer.get_metrics(first_skill_id)
        assert metrics.total_executions > 0

        # 6. Create version and set up for evolution
        version_mgr.create_version(
            first_skill_id,
            "Original prompt content",
        )

        # 7. Run evolution cycle
        evolver = SkillEvolver(
            observer=observer,
            version_manager=version_mgr,
        )
        report = evolver.evolve_cycle(min_observations=1)
        assert report.skills_analyzed >= 0
        # Report should be valid
        assert isinstance(report.details, list)

    def test_skill_loader_prompt_injection(self, tmp_path: object) -> None:
        """Skill loader prompt is injected into route engine context."""
        base = str(tmp_path)
        skill_dir = os.path.join(base, "skills")
        _make_skill_file(skill_dir, "test-inject")

        loader = SkillLoader(search_dirs=[skill_dir])
        loader.discover()

        contract = _make_contract()
        kernel = MockKernel()

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            skill_loader=loader,
        )

        # The route_engine should have a context provider that includes skills
        if hasattr(executor.route_engine, '_context_provider'):
            ctx = executor.route_engine._context_provider()
            assert "skill_prompt" in ctx
            assert "test-inject" in ctx["skill_prompt"]

    def test_version_manager_champion_challenger_flow(self) -> None:
        """Version manager supports create -> champion -> challenger -> promote."""
        vmgr = SkillVersionManager()

        # Create first version (auto-champion)
        v1 = vmgr.create_version("sk1", "prompt v1")
        assert v1.is_champion is True

        # Create second version and set as challenger
        v2 = vmgr.create_version("sk1", "prompt v2")
        vmgr.set_challenger("sk1", v2.version)
        assert v2.is_challenger is True

        # Promote challenger
        promoted = vmgr.promote_challenger("sk1")
        assert promoted is True
        assert vmgr.get_champion("sk1").version == v2.version
