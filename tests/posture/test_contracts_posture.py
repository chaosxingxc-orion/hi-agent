"""Posture-matrix tests for contracts module callsites (Rule 11).

Covers:
  hi_agent/contracts/extension_manifest.py — production_eligibility,
      _validate_enforcement_fields, enable
  hi_agent/evolve/contracts.py — __post_init__ in RunRetrospective,
      CalibrationSignal, ProjectRetrospective, EvolutionTrial

Test function names are test_<source_function_name> so check_posture_coverage.py
matches them to callsite function names.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# Concrete manifest helpers (ExtensionManifest is a Protocol, not instantiable)
# ---------------------------------------------------------------------------

def _make_safe_manifest(name: str = "ext-a", version: str = "1.0"):
    """Concrete manifest: safe, no dangerous caps."""
    from hi_agent.contracts.extension_manifest import ExtensionManifestMixin

    class _M(ExtensionManifestMixin):
        def __init__(self):
            self.name = name
            self.version = version
            self.description = "test"
            self.entry_point = "test.entry:run"
            self.manifest_kind = "plugin"
            self.schema_version = 1
            self.posture_support = {"dev": True, "research": True, "prod": True}
            self.required_posture = "any"
            self.tenant_scope = "global"
            self.dangerous_capabilities = []
            self.config_schema = None

        def to_manifest_dict(self):
            return {"name": self.name, "version": self.version}

    return _M()


def _make_dangerous_manifest(name: str = "ext-d", version: str = "1.0"):
    """Concrete manifest: has dangerous_capabilities, no config_schema."""
    from hi_agent.contracts.extension_manifest import ExtensionManifestMixin

    class _D(ExtensionManifestMixin):
        def __init__(self):
            self.name = name
            self.version = version
            self.description = "dangerous"
            self.entry_point = "test.entry:run"
            self.manifest_kind = "plugin"
            self.schema_version = 1
            self.posture_support = {"dev": True, "research": False, "prod": False}
            self.required_posture = "any"
            self.tenant_scope = "global"
            self.dangerous_capabilities = ["shell_exec"]
            self.config_schema = None

        def to_manifest_dict(self):
            return {"name": self.name, "version": self.version}

    return _D()


def _run_retro_kwargs(tenant_id: str = "") -> dict:
    return {
        "run_id": "r1", "task_id": "t1", "task_family": "test", "outcome": "completed",
        "stages_completed": [], "stages_failed": [], "branches_explored": 0,
        "branches_pruned": 0, "total_actions": 0, "failure_codes": [],
        "duration_seconds": 1.0, "project_id": "p1", "tenant_id": tenant_id,
    }


# ---------------------------------------------------------------------------
# extension_manifest.production_eligibility
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,dangerous,expect_eligible", [
    ("dev", False, True),
    ("dev", True, True),      # dev: dangerous+no-schema still eligible
    ("research", False, True),
    ("research", True, False), # strict: dangerous+no-schema blocked
    ("prod", False, True),
    ("prod", True, False),
])
def test_production_eligibility(monkeypatch, posture_name, dangerous, expect_eligible):
    """Posture-matrix test for production_eligibility.

    dev: always eligible regardless of dangerous_capabilities.
    research/prod: dangerous extension without config_schema is blocked.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    mf = _make_dangerous_manifest() if dangerous else _make_safe_manifest()
    eligible, _ = mf.production_eligibility(Posture(posture_name))
    assert eligible is expect_eligible


# ---------------------------------------------------------------------------
# extension_manifest._validate_enforcement_fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,should_raise", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__validate_enforcement_fields(monkeypatch, posture_name, should_raise):
    """Posture-matrix test for _validate_enforcement_fields.

    dev: missing enforcement fields warn but do not raise.
    research/prod: missing fields raise ValueError.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.extension_manifest import ExtensionRegistry

    class _BareManifest:
        """Has posture_support but is missing required enforcement fields."""
        name = f"bare-{posture_name}"
        version = "1.0"
        manifest_kind = "plugin"
        # Intentionally missing: required_posture, tenant_scope,
        # dangerous_capabilities, config_schema

        def __init__(self) -> None:
            self.posture_support = {"dev": True, "research": True, "prod": True}

    reg = ExtensionRegistry()
    if should_raise:
        with pytest.raises(ValueError):
            reg.register(_BareManifest(), posture=Posture(posture_name))
    else:
        reg.register(_BareManifest(), posture=Posture(posture_name))


# ---------------------------------------------------------------------------
# extension_manifest.enable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,needs_approval", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_enable(monkeypatch, posture_name, needs_approval):
    """Posture-matrix test for enable.

    dev: dangerous extension can be enabled without approval.
    research/prod: dangerous extension requires human gate approval.
    Safe extensions always enable.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.extension_manifest import (
        ExtensionRegistry,
        ExtensionRequiresHumanApproval,
    )

    p = Posture(posture_name)
    reg = ExtensionRegistry()

    # Safe extension always enables
    safe = _make_safe_manifest(name=f"safe-{posture_name}", version="1.0")
    reg.register(safe, posture=p)
    reg.enable(f"safe-{posture_name}", "1.0", posture=p)

    # Dangerous extension
    danger = _make_dangerous_manifest(name=f"danger-{posture_name}", version="1.0")
    reg.register(danger, posture=p)
    if needs_approval:
        with pytest.raises(ExtensionRequiresHumanApproval):
            reg.enable(f"danger-{posture_name}", "1.0", posture=p)
    else:
        reg.enable(f"danger-{posture_name}", "1.0", posture=p)


# ---------------------------------------------------------------------------
# evolve/contracts __post_init__ posture checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,empty_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__post_init__run_retrospective(monkeypatch, posture_name, empty_raises):
    """Posture-matrix: RunRetrospective.__post_init__ — tenant_id required in strict."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.evolve.contracts import RunRetrospective

    rr = RunRetrospective(**_run_retro_kwargs(tenant_id="t-abc"))
    assert rr.tenant_id == "t-abc"

    if empty_raises:
        with pytest.raises(ValueError, match="tenant_id"):
            RunRetrospective(**_run_retro_kwargs(tenant_id=""))
    else:
        rr2 = RunRetrospective(**_run_retro_kwargs(tenant_id=""))
        assert rr2.tenant_id == ""


@pytest.mark.parametrize("posture_name,empty_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__post_init__calibration_signal(monkeypatch, posture_name, empty_raises):
    """Posture-matrix: CalibrationSignal.__post_init__ — tenant_id required in strict."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.evolve.contracts import CalibrationSignal

    cs = CalibrationSignal(project_id="p1", run_id="r1", model="gpt", tier="t1", tenant_id="t-abc")
    assert cs.tenant_id == "t-abc"

    if empty_raises:
        with pytest.raises(ValueError, match="tenant_id"):
            CalibrationSignal(project_id="p1", run_id="r1", model="gpt", tier="t1", tenant_id="")
    else:
        cs2 = CalibrationSignal(project_id="p1", run_id="r1", model="gpt", tier="t1", tenant_id="")
        assert cs2.tenant_id == ""


@pytest.mark.parametrize("posture_name,empty_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__post_init__project_retrospective(monkeypatch, posture_name, empty_raises):
    """Posture-matrix: ProjectRetrospective.__post_init__ — tenant_id required in strict."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.evolve.contracts import ProjectRetrospective

    pr = ProjectRetrospective(project_id="p1", run_ids=["r1"], tenant_id="t-abc")
    assert pr.tenant_id == "t-abc"

    if empty_raises:
        with pytest.raises(ValueError, match="tenant_id"):
            ProjectRetrospective(project_id="p1", run_ids=["r1"], tenant_id="")
    else:
        pr2 = ProjectRetrospective(project_id="p1", run_ids=["r1"], tenant_id="")
        assert pr2.tenant_id == ""


@pytest.mark.parametrize("posture_name,empty_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__post_init__evolution_trial(monkeypatch, posture_name, empty_raises):
    """Posture-matrix: EvolutionTrial.__post_init__ — tenant_id required in strict."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.evolve.contracts import EvolutionTrial

    def _make_trial(tenant_id: str = ""):
        return EvolutionTrial(
            experiment_id="e1", capability_name="cap", baseline_version="1.0",
            candidate_version="2.0", metric_name="quality",
            started_at="2026-01-01T00:00:00Z", status="active", tenant_id=tenant_id,
        )

    trial = _make_trial("t-abc")
    assert trial.tenant_id == "t-abc"

    if empty_raises:
        with pytest.raises(ValueError, match="tenant_id"):
            _make_trial("")
    else:
        trial2 = _make_trial("")
        assert trial2.tenant_id == ""
