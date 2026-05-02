"""W19-A3: Scope-aware gate_warn / gate_fail / gate_missing tests.

Verifies that architectural-constraint gates (soak_evidence,
observability_spine_completeness, chaos_runtime_coupling) are excluded from
cap_factors when computing current_verified_readiness, while genuine
engineering gates (pytest_skip_discipline, multistatus_gates) are NOT excluded.

This prevents double-counting: the 7x24 architectural deferral should only
affect seven_by_twenty_four_operational_readiness, never current_verified_readiness.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

# Make scripts/ importable without installing the package.
_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from build_release_manifest import _ARCH_CONSTRAINT_GATES, _compute_cap

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gates(**overrides: str) -> dict:
    """Build a minimal gate dict where every gate passes by default.

    Keyword arguments override specific gate statuses.
    """
    base_keys = [
        "layering", "vocab", "route_scope", "expired_waivers",
        "doc_canonical", "doc_consistency", "wave_tags", "rule6_warnings",
        "t3_freshness", "boundary", "deprecated_api", "durable_wiring",
        "metrics_cardinality", "slo_health", "allowlist_discipline",
        "verification_artifacts", "targeted_default_path", "clean_env",
        "validate_before_mutate", "select_completeness", "silent_degradation",
        "metric_producers", "downstream_response_format",
        "evidence_provenance", "allowlist_universal", "noqa_discipline",
        "pytest_skip_discipline", "closure_taxonomy", "multistatus_gates",
        "observability_spine_completeness", "soak_evidence",
        "chaos_runtime_coupling", "no_hardcoded_wave",
    ]
    gates: dict = {k: {"status": "pass"} for k in base_keys}
    for k, v in overrides.items():
        gates[k] = {"status": v}
    return gates


# ---------------------------------------------------------------------------
# Tests 1-3: Architectural gates must NOT contribute gate_warn to verified
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gate_key", [
    "soak_evidence",
    "observability_spine_completeness",
    "chaos_runtime_coupling",
])
def test_arch_gate_deferred_does_not_affect_verified(gate_key: str) -> None:
    """When an architectural gate is deferred, current_verified_readiness
    must NOT include a gate_warn/gate_fail factor for it.

    The 7x24 score may be capped, but verified (engineering readiness) must
    remain free of the architectural deferral penalty.
    """
    gates = _make_gates(**{gate_key: "deferred"})

    _cap_val, _reason, cap_factors = _compute_cap(
        gates,
        is_dirty=False,
        t3_stale=False,
        expired_allowlist=0,
        tier="current_verified_readiness",
    )

    # gate_warn must not mention the arch gate key
    gate_warn_factors = [f for f in cap_factors if "gate_warn" in f]
    for gw_factor in gate_warn_factors:
        assert gate_key not in gw_factor, (
            f"Architectural gate '{gate_key}' (deferred) leaked into "
            f"current_verified_readiness cap factor: {gw_factor!r}\n"
            f"All cap_factors: {cap_factors}"
        )

    gate_fail_factors = [f for f in cap_factors if "gate_fail" in f]
    for gf_factor in gate_fail_factors:
        assert gate_key not in gf_factor, (
            f"Architectural gate '{gate_key}' (deferred) leaked into "
            f"gate_fail cap factor: {gf_factor!r}"
        )


def test_7x24_capped_when_arch_evidence_missing(monkeypatch, tmp_path) -> None:
    """W28+: 7x24 is governed by a single architectural rule
    (`architectural_seven_by_twenty_four`) sourced from
    docs/verification/<sha>-arch-7x24.json. The legacy single-purpose caps
    (`observability_spine_incomplete`, `chaos_non_runtime_coupled`,
    `soak_24h_missing`) were retired -- deferring those underlying gates no
    longer caps 7x24 directly. The cap fires when arch-7x24 evidence is
    absent OR shows any failing assertion.
    """
    import shutil

    import build_release_manifest as brm

    # Mirror the score_caps.yaml under tmp so _load_score_caps still resolves,
    # then point ROOT to tmp so the evidence search finds an empty directory.
    real_yaml = brm.ROOT / "docs" / "governance" / "score_caps.yaml"
    fake_gov = tmp_path / "docs" / "governance"
    fake_ver = tmp_path / "docs" / "verification"
    fake_gov.mkdir(parents=True)
    fake_ver.mkdir(parents=True)
    shutil.copy(real_yaml, fake_gov / "score_caps.yaml")
    monkeypatch.setattr(brm, "ROOT", tmp_path)

    gates = _make_gates()
    _cap_val, _reason, cap_factors_7x24 = _compute_cap(
        gates,
        is_dirty=False,
        t3_stale=False,
        expired_allowlist=0,
        tier="seven_by_twenty_four_operational_readiness",
    )

    assert any("architectural_seven_by_twenty_four" in f for f in cap_factors_7x24), (
        f"Expected architectural_seven_by_twenty_four cap when evidence is missing, "
        f"got cap_factors_7x24={cap_factors_7x24}"
    )


@pytest.mark.parametrize("gate_key", [
    "soak_evidence",
    "observability_spine_completeness",
    "chaos_runtime_coupling",
])
def test_underlying_arch_gate_deferral_does_not_directly_cap_7x24(gate_key: str) -> None:
    """W28+ guard against regression: deferring `soak_evidence`,
    `observability_spine_completeness`, or `chaos_runtime_coupling` MUST NOT
    by itself add a cap_factor to the 7x24 tier. Those concerns are now
    routed through the unified architectural assertion check
    (scripts/run_arch_7x24.py) instead of three single-purpose caps.
    """
    gates = _make_gates(**{gate_key: "deferred"})

    _cap_val, _reason, cap_factors_7x24 = _compute_cap(
        gates,
        is_dirty=False,
        t3_stale=False,
        expired_allowlist=0,
        tier="seven_by_twenty_four_operational_readiness",
    )

    legacy_caps = {
        "soak_24h_missing", "soak_24h_pending",
        "observability_spine_incomplete", "chaos_non_runtime_coupled",
    }
    leaked = [f for f in cap_factors_7x24 if any(c in f for c in legacy_caps)]
    assert not leaked, (
        f"Legacy single-purpose 7x24 cap fired for '{gate_key}' deferral: "
        f"{leaked}. These caps were retired W28; only "
        f"architectural_seven_by_twenty_four should govern the 7x24 tier."
    )


# ---------------------------------------------------------------------------
# Test 4: Engineering gate (pytest_skip_discipline) deferred MUST still cap verified
# ---------------------------------------------------------------------------

def test_engineering_gate_deferred_still_caps_verified() -> None:
    """When pytest_skip_discipline is deferred, current_verified_readiness
    MUST still include a gate_warn factor.  This gate is an engineering
    constraint, not an architectural one.
    """
    gates = _make_gates(pytest_skip_discipline="deferred")

    _cap_val, _reason, cap_factors = _compute_cap(
        gates,
        is_dirty=False,
        t3_stale=False,
        expired_allowlist=0,
        tier="current_verified_readiness",
    )

    gate_warn_factors = [f for f in cap_factors if "gate_warn" in f]
    assert gate_warn_factors, (
        "Expected gate_warn cap factor for deferred pytest_skip_discipline, "
        f"but none found. cap_factors={cap_factors}"
    )
    matched = any("pytest_skip_discipline" in f for f in gate_warn_factors)
    assert matched, (
        f"pytest_skip_discipline not mentioned in gate_warn factors: {gate_warn_factors}"
    )


# ---------------------------------------------------------------------------
# Test 5: Engineering gate (multistatus_gates) deferred MUST still cap verified
# ---------------------------------------------------------------------------

def test_multistatus_gates_deferred_still_caps_verified() -> None:
    """When multistatus_gates is deferred, current_verified_readiness
    MUST still include a gate_warn factor.
    """
    gates = _make_gates(multistatus_gates="deferred")

    _cap_val, _reason, cap_factors = _compute_cap(
        gates,
        is_dirty=False,
        t3_stale=False,
        expired_allowlist=0,
        tier="current_verified_readiness",
    )

    gate_warn_factors = [f for f in cap_factors if "gate_warn" in f]
    assert gate_warn_factors, (
        "Expected gate_warn cap factor for deferred multistatus_gates, "
        f"but none found. cap_factors={cap_factors}"
    )
    matched = any("multistatus_gates" in f for f in gate_warn_factors)
    assert matched, (
        f"multistatus_gates not mentioned in gate_warn factors: {gate_warn_factors}"
    )


# ---------------------------------------------------------------------------
# Invariant: _ARCH_CONSTRAINT_GATES must contain exactly the expected keys
# ---------------------------------------------------------------------------

def test_arch_constraint_gates_set_is_correct() -> None:
    """_ARCH_CONSTRAINT_GATES must contain the three expected gate keys and
    nothing else, so future additions require a deliberate code change.
    """
    expected = {"soak_evidence", "observability_spine_completeness", "chaos_runtime_coupling"}
    assert expected == _ARCH_CONSTRAINT_GATES, (
        f"_ARCH_CONSTRAINT_GATES changed unexpectedly. "
        f"Expected {expected}, got {_ARCH_CONSTRAINT_GATES}"
    )
