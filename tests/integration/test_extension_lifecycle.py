"""Integration tests — C12 ExtensionRegistry upgrade/rollback + ExperimentStore rollback.

Layer 2 (Integration): real components wired together; no mocks on the subsystem under test.

Tests:
    test_register_then_upgrade_then_rollback -- full lifecycle end-to-end
    test_rollback_without_prior_version_raises -- KeyError when no prior version tracked
    test_experiment_rollback -- InMemoryExperimentStore marks experiment as rolled_back
    test_cli_extensions_list -- CLI list subcommand produces non-empty output format
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime

import pytest
from hi_agent.contracts.extension_manifest import ExtensionRegistry
from hi_agent.evolve.contracts import EvolutionTrial
from hi_agent.evolve.experiment_store import InMemoryExperimentStore
from hi_agent.plugins.manifest import PluginManifest


def _make_manifest(name: str, version: str) -> PluginManifest:
    """Build a minimal valid PluginManifest for testing."""
    return PluginManifest(
        name=name,
        version=version,
        description="test manifest",
        manifest_kind="plugin",
        posture_support={"dev": True, "research": True, "prod": True},
        required_posture="any",
        tenant_scope="tenant",
        dangerous_capabilities=[],
        config_schema=None,
    )


def _make_trial(experiment_id: str, status: str = "active") -> EvolutionTrial:
    """Build a minimal EvolutionTrial for testing."""
    return EvolutionTrial(
        experiment_id=experiment_id,
        capability_name="test-cap",
        baseline_version="1.0.0",
        candidate_version="2.0.0",
        metric_name="accuracy",
        started_at=datetime.now(UTC).isoformat(),
        status=status,
        tenant_id="",
        project_id="proj-1",
        run_id="run-1",
    )


# ---------------------------------------------------------------------------
# ExtensionRegistry lifecycle
# ---------------------------------------------------------------------------


def test_register_then_upgrade_then_rollback():
    """Full lifecycle: register v1, upgrade to v2, rollback to v1.

    Verifies:
    - After register: v1 present, v2 absent.
    - After upgrade: v2 present, v1 absent, _previous[name] == v1 manifest.
    - After rollback: v1 present, v2 absent, _previous[name] cleared.
    """
    registry = ExtensionRegistry()
    name = "lifecycle-ext"

    v1 = _make_manifest(name, "1.0.0")
    v2 = _make_manifest(name, "2.0.0")

    # Register v1.
    registry.register(v1)
    assert registry.get(name, "1.0.0") is v1
    assert registry.get(name, "2.0.0") is None

    # Upgrade to v2.
    registry.upgrade(name, "2.0.0", v2)
    assert registry.get(name, "2.0.0") is v2
    assert registry.get(name, "1.0.0") is None
    assert name in registry._previous

    # Rollback to v1.
    registry.rollback(name)
    assert registry.get(name, "1.0.0") is v1
    assert registry.get(name, "2.0.0") is None
    assert name not in registry._previous


def test_rollback_without_prior_version_raises():
    """rollback() raises KeyError when no prior version is tracked for the extension."""
    registry = ExtensionRegistry()
    name = "no-history-ext"

    manifest = _make_manifest(name, "1.0.0")
    registry.register(manifest)

    with pytest.raises(KeyError, match="no prior version tracked"):
        registry.rollback(name)


def test_upgrade_nonexistent_extension_raises():
    """upgrade() raises KeyError when the named extension is not registered."""
    registry = ExtensionRegistry()
    new_manifest = _make_manifest("ghost-ext", "2.0.0")

    with pytest.raises(KeyError, match="no extension named"):
        registry.upgrade("ghost-ext", "2.0.0", new_manifest)


def test_upgrade_invalid_new_manifest_reverts_registry():
    """upgrade() rolls back the deletion if the new manifest fails validation."""
    registry = ExtensionRegistry()
    name = "upgrade-fail-ext"

    v1 = _make_manifest(name, "1.0.0")
    registry.register(v1)

    # Build a broken manifest (empty name will fail register validation).
    broken = _make_manifest("", "2.0.0")

    with pytest.raises(ValueError):
        registry.upgrade(name, "2.0.0", broken)

    # v1 must still be present after the failed upgrade.
    assert registry.get(name, "1.0.0") is v1
    assert name not in registry._previous


# ---------------------------------------------------------------------------
# ExperimentStore rollback
# ---------------------------------------------------------------------------


def test_experiment_rollback():
    """InMemoryExperimentStore.rollback() marks an active experiment as rolled_back."""
    store = InMemoryExperimentStore()
    trial = _make_trial("exp-001", status="active")
    store.start_experiment(trial)

    store.rollback("exp-001")

    result = store.get_experiment("exp-001")
    assert result is not None
    assert result.status == "rolled_back"


def test_experiment_rollback_already_terminal_raises():
    """rollback() raises ValueError when the experiment is already in a terminal state."""
    store = InMemoryExperimentStore()
    trial = _make_trial("exp-002", status="active")
    store.start_experiment(trial)
    store.complete_experiment("exp-002", "completed")

    with pytest.raises(ValueError, match="already in terminal state"):
        store.rollback("exp-002")


def test_experiment_rollback_not_found_raises():
    """rollback() raises KeyError when the experiment ID does not exist."""
    store = InMemoryExperimentStore()

    with pytest.raises(KeyError, match="not found"):
        store.rollback("does-not-exist")


# ---------------------------------------------------------------------------
# CLI extensions list
# ---------------------------------------------------------------------------


def test_cli_extensions_list():
    """CLI `extensions list` runs without error and produces well-formed output.

    Registers nothing (global registry may be empty); asserts the command
    exits 0 and outputs either the header-free list or "No extensions registered."
    """
    result = subprocess.run(
        [sys.executable, "-m", "hi_agent", "extensions", "list"],
        capture_output=True,
        text=True,
    )
    # exit 0 means the subcommand wired up correctly
    assert result.returncode == 0, (
        f"extensions list exited {result.returncode}. stderr={result.stderr!r}"
    )
    # Output must be a non-error string (either "No extensions registered." or a list of entries)
    combined = result.stdout + result.stderr
    assert "error" not in combined.lower() or "No extensions registered" in result.stdout, (
        f"Unexpected error in output: {combined!r}"
    )
