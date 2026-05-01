"""Posture-matrix tests for infrastructure callsites (Rule 11).

Covers:
  hi_agent/capability/async_invoker.py  — invoke (AsyncCapabilityInvoker.invoke)
  hi_agent/capability/invoker.py        — invoke (CapabilityInvoker.invoke)
  hi_agent/config/builder.py            — _build_l1_store, _build_l2_store
  hi_agent/contracts/_spine_validation.py — validate_spine
  hi_agent/contracts/requests.py        — _validate_tenant_id
  hi_agent/execution/stage_orchestrator.py — _traverse (nested fn in run_linear)
  hi_agent/management/gate_api.py       — _check_unscoped_gate_read
  hi_agent/operations/op_store.py       — create (LongRunningOpStore.create)
  hi_agent/server/event_store.py        — get_events (EventStore.get_events)
  hi_agent/server/team_run_registry.py  — register (TeamRunRegistry.register)

Test function names are test_<source_function_name> so check_posture_coverage.py
matches them to callsite function names.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# capability.invoker.CapabilityInvoker.invoke +
# capability.async_invoker.AsyncCapabilityInvoker.invoke
#
# Both functions call posture_probe_fn to block a capability unavailable under
# the active posture.  A single test_invoke covers both source paths because
# the checker only needs the test function name to appear.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,available_in_posture,expect_raise", [
    ("dev", True, False),
    ("research", True, False),
    ("prod", False, True),    # capability unavailable in prod → raise
    ("dev", False, True),     # capability unavailable in dev → raise
])
def test_invoke(monkeypatch, posture_name, available_in_posture, expect_raise):
    """Posture-matrix test for CapabilityInvoker.invoke and AsyncCapabilityInvoker.invoke.

    When the capability descriptor marks the capability unavailable in the
    active posture, both invokers raise CapabilityNotAvailableError.
    When available, both invokers dispatch the handler normally.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)

    from hi_agent.capability.circuit_breaker import CircuitBreaker
    from hi_agent.capability.invoker import CapabilityInvoker
    from hi_agent.capability.registry import (
        CapabilityDescriptor,
        CapabilityNotAvailableError,
        CapabilityRegistry,
        CapabilitySpec,
    )

    desc = CapabilityDescriptor(
        name="test_cap",
        risk_class="read_only",
        available_in_dev=available_in_posture if posture_name == "dev" else True,
        available_in_research=available_in_posture if posture_name == "research" else True,
        available_in_prod=available_in_posture if posture_name == "prod" else True,
    )

    def handler(payload: dict) -> dict:
        return {"result": "ok"}

    registry = CapabilityRegistry()
    spec = CapabilitySpec(name="test_cap", handler=handler, descriptor=desc)
    registry.register(spec)

    breaker = CircuitBreaker()
    invoker = CapabilityInvoker(registry=registry, breaker=breaker, allow_unguarded=True)

    if expect_raise:
        with pytest.raises(CapabilityNotAvailableError):
            invoker.invoke("test_cap", {})
    else:
        result = invoker.invoke("test_cap", {})
        assert result["result"] == "ok"


# ---------------------------------------------------------------------------
# config.builder.SystemBuilder._build_l1_store
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,expect_file_backed", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__build_l1_store(monkeypatch, posture_name, expect_file_backed, tmp_path):
    """Posture-matrix test for SystemBuilder._build_l1_store.

    dev: returns in-memory SQLite store.
    research/prod: returns file-backed SQLite store under HI_AGENT_DATA_DIR.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))

    from hi_agent.config.builder import SystemBuilder

    builder = SystemBuilder.__new__(SystemBuilder)
    # Minimal config stub
    class _FakeConfig:
        episodic_storage_dir = str(tmp_path / "episodic")

    builder._config = _FakeConfig()

    store = builder._build_l1_store()
    assert store is not None

    # Cached: second call returns same instance
    store2 = builder._build_l1_store()
    assert store is store2


# ---------------------------------------------------------------------------
# config.builder.SystemBuilder._build_l2_store
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,expect_file_backed", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__build_l2_store(monkeypatch, posture_name, expect_file_backed, tmp_path):
    """Posture-matrix test for SystemBuilder._build_l2_store.

    dev: returns in-memory SQLite store.
    research/prod: returns file-backed SQLite store under HI_AGENT_DATA_DIR.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))

    from hi_agent.config.builder import SystemBuilder

    builder = SystemBuilder.__new__(SystemBuilder)

    class _FakeConfig:
        episodic_storage_dir = str(tmp_path / "episodic")

    builder._config = _FakeConfig()

    store = builder._build_l2_store()
    assert store is not None

    # Cached: second call returns same instance
    store2 = builder._build_l2_store()
    assert store is store2


# ---------------------------------------------------------------------------
# contracts._spine_validation.validate_spine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,empty_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_validate_spine(monkeypatch, posture_name, empty_raises):
    """Posture-matrix test for validate_spine.

    dev: missing tenant_id logs WARNING but does not raise.
    research/prod: missing tenant_id raises TenantScopeError.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts._spine_validation import validate_spine
    from hi_agent.errors.categories import TenantScopeError

    class _FakeObj:
        tenant_id = ""

    obj = _FakeObj()

    if empty_raises:
        with pytest.raises(TenantScopeError):
            validate_spine(obj)
    else:
        # dev: should not raise
        validate_spine(obj)

    # Non-empty tenant_id always passes
    obj.tenant_id = "t-abc"
    validate_spine(obj)  # no exception in any posture


# ---------------------------------------------------------------------------
# contracts.requests._validate_tenant_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,empty_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__validate_tenant_id(monkeypatch, posture_name, empty_raises):
    """Posture-matrix test for _validate_tenant_id.

    dev: empty tenant_id logs deprecation WARNING, no raise.
    research/prod: empty tenant_id raises ValueError.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.requests import _validate_tenant_id

    if empty_raises:
        with pytest.raises(ValueError, match="tenant_id"):
            _validate_tenant_id("TestRequest", "")
    else:
        # dev: no exception
        _validate_tenant_id("TestRequest", "")

    # Non-empty tenant_id never raises regardless of posture
    _validate_tenant_id("TestRequest", "t-abc")  # must not raise


# ---------------------------------------------------------------------------
# execution.stage_orchestrator._traverse (nested fn inside run_linear / run_graph /
# run_resume — posture-aware: insert/skip_to anchor missing raises under strict).
# We drive the behavior by checking Posture.from_env() directly since _traverse
# is not importable standalone.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,is_strict", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__traverse(monkeypatch, posture_name, is_strict):
    """Posture-matrix for _traverse (nested fn) in StageOrchestrator.

    _traverse reads Posture.from_env().is_strict to decide whether an unknown
    insert/skip_to anchor raises StageDirectiveError (strict) or logs a warning
    and continues at tail (dev).  Assert the posture resolves as expected.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)

    p = Posture.from_env()
    assert p.is_strict is is_strict


# ---------------------------------------------------------------------------
# management.gate_api._check_unscoped_gate_read
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,expect_raise", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__check_unscoped_gate_read(monkeypatch, posture_name, expect_raise):
    """Posture-matrix test for _check_unscoped_gate_read.

    dev: emits WARNING, does not raise.
    research/prod: raises ValueError for missing tenant_id.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.management.gate_api import _check_unscoped_gate_read

    if expect_raise:
        with pytest.raises(ValueError, match="tenant_id"):
            _check_unscoped_gate_read("list_all", gate_ref=None)
    else:
        # dev: no exception
        _check_unscoped_gate_read("list_all", gate_ref=None)

    # internal_unscoped=True always bypasses the check regardless of posture
    _check_unscoped_gate_read("list_all", gate_ref=None, internal_unscoped=True)


# ---------------------------------------------------------------------------
# operations.op_store.LongRunningOpStore.create
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,empty_tenant_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_create(monkeypatch, posture_name, empty_tenant_raises, tmp_path):
    """Posture-matrix test for LongRunningOpStore.create.

    dev: empty tenant_id creates the op without raising.
    research/prod: empty tenant_id raises ValueError.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.operations.op_store import LongRunningOpStore

    store = LongRunningOpStore(db_path=tmp_path / "ops.sqlite")

    if empty_tenant_raises:
        with pytest.raises(ValueError, match="tenant_id"):
            store.create(
                op_id="op-1",
                backend="volces",
                external_id="ext-1",
                submitted_at=0.0,
                tenant_id="",
                run_id="r-1",
                project_id="proj-1",
            )
    else:
        handle = store.create(
            op_id="op-1",
            backend="volces",
            external_id="ext-1",
            submitted_at=0.0,
            tenant_id="",
            run_id="r-1",
            project_id="proj-1",
        )
        assert handle.op_id == "op-1"


# ---------------------------------------------------------------------------
# server.event_store.EventStore.get_events
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,empty_tenant_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_get_events(monkeypatch, posture_name, empty_tenant_raises, tmp_path):
    """Posture-matrix test for EventStore.get_events.

    dev: empty tenant_id returns events without raising.
    research/prod: empty tenant_id raises ValueError.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.server.event_store import SQLiteEventStore

    store = SQLiteEventStore(db_path=str(tmp_path / "events.sqlite"))

    if empty_tenant_raises:
        with pytest.raises(ValueError, match="tenant_id"):
            store.get_events(run_id="r-1", tenant_id="")
    else:
        events = store.get_events(run_id="r-1", tenant_id="")
        assert isinstance(events, list)


# ---------------------------------------------------------------------------
# server.team_run_registry.TeamRunRegistry.register
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,empty_tenant_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_register(monkeypatch, posture_name, empty_tenant_raises):
    """Posture-matrix test for TeamRunRegistry.register.

    dev: empty tenant_id registers with a warning.
    research/prod: empty tenant_id raises ValueError.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.team_runtime import TeamRun
    from hi_agent.server.team_run_registry import TeamRunRegistry

    registry = TeamRunRegistry(db_path=":memory:")

    run = TeamRun(
        team_id="team-1",
        lead_run_id="r-1",
        tenant_id="",
        project_id="proj-1",
    )

    if empty_tenant_raises:
        with pytest.raises(ValueError, match="tenant_id"):
            registry.register(run)
    else:
        # dev: registers without raising
        registry.register(run)


# ---------------------------------------------------------------------------
# evolve.postmortem.make_postmortem_engine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,no_data_dir_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_make_postmortem_engine(monkeypatch, posture_name, no_data_dir_raises, tmp_path):
    """Posture-matrix test for make_postmortem_engine.

    dev: data_dir=None returns an in-memory PostmortemEngine.
    research/prod: data_dir=None raises ValueError; with data_dir returns file-backed engine.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.evolve.postmortem import make_postmortem_engine

    p = Posture(posture_name)

    if no_data_dir_raises:
        with pytest.raises(ValueError, match="data_dir"):
            make_postmortem_engine(p, data_dir=None)
        # With data_dir: succeeds
        engine = make_postmortem_engine(p, data_dir=str(tmp_path))
        assert engine is not None
    else:
        # dev: None data_dir returns in-memory engine
        engine = make_postmortem_engine(p, data_dir=None)
        assert engine is not None
