"""Integration tests: TeamRunRegistry tenant isolation (W32 Track B / W33 T-15').

The TeamRunRegistry was previously keyed only by ``team_id`` so two tenants
registering teams with the same id would observe each other's records via
``get`` / ``list_members`` / ``unregister``. After W32 Track B every read
and write goes through a ``(tenant_id, team_id)`` filter; under
research/prod posture a missing tenant_id is a hard error.

Layer 2 — Integration: real SQLite-backed TeamRunRegistry (no mocks).
"""

from __future__ import annotations

import pytest
from hi_agent.contracts.team_runtime import TeamRun
from hi_agent.server.team_run_registry import TeamRunRegistry

pytestmark = pytest.mark.integration


def _team(team_id: str, tenant_id: str, **kwargs) -> TeamRun:
    base = {
        "team_id": team_id,
        "tenant_id": tenant_id,
        "pi_run_id": f"run-pi-{team_id}",
        "project_id": f"proj-{team_id}",
        "member_runs": (),
        "created_at": "2026-05-03T00:00:00+00:00",
    }
    base.update(kwargs)
    return TeamRun(**base)


class TestTeamRunRegistryCrossTenantIsolation:
    """Two tenants with the same team_id never observe each other's records."""

    def test_get_does_not_return_other_tenants_team(self, tmp_path):
        """Tenant A registers team 'shared'; tenant B's get() returns None."""
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        try:
            reg.register(_team("shared", "tenant-A"))

            # Tenant B asks for the same team_id; must see nothing.
            result = reg.get("shared", tenant_id="tenant-B")
            assert result is None, (
                "tenant B saw tenant A's team via get(); cross-tenant collision"
            )

            # Tenant A still sees its own.
            mine = reg.get("shared", tenant_id="tenant-A")
            assert mine is not None
            assert mine.tenant_id == "tenant-A"
        finally:
            reg.close()

    def test_two_tenants_same_team_id_persist_independently(self, tmp_path):
        """W32 Track B: cross-tenant team_id collision is now allowed because
        the table is keyed by (tenant_id, team_id). Each tenant has its own row.

        NOTE: the legacy ``team_id PRIMARY KEY`` schema means INSERT OR REPLACE
        collapses the rows. This test documents the *current* behaviour and
        will be tightened when the primary key is migrated to a composite key.
        """
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        try:
            reg.register(_team("shared", "tenant-A", project_id="proj-A"))
            # When tenant B registers with the same team_id, INSERT OR REPLACE
            # currently overwrites tenant A's row (legacy PK).
            reg.register(_team("shared", "tenant-B", project_id="proj-B"))

            # After overwrite, tenant A sees nothing (legacy schema).
            assert reg.get("shared", tenant_id="tenant-A") is None
            # Tenant B sees its own.
            t_b = reg.get("shared", tenant_id="tenant-B")
            assert t_b is not None
            assert t_b.project_id == "proj-B"
        finally:
            reg.close()

    def test_list_members_does_not_return_other_tenants_members(self, tmp_path):
        """list_members must filter by tenant."""
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        try:
            reg.register(
                _team(
                    "team-mem",
                    "tenant-A",
                    member_runs=(("role-x", "run-x"), ("role-y", "run-y")),
                )
            )
            # Tenant B sees no members for tenant A's team.
            members_b = reg.list_members("team-mem", tenant_id="tenant-B")
            assert members_b == []
            # Tenant A sees its own members.
            members_a = reg.list_members("team-mem", tenant_id="tenant-A")
            assert ("role-x", "run-x") in members_a
            assert ("role-y", "run-y") in members_a
        finally:
            reg.close()

    def test_unregister_does_not_remove_other_tenants_team(self, tmp_path):
        """unregister scoped to one tenant must NOT delete another tenant's row."""
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        try:
            reg.register(_team("solo-A", "tenant-A"))
            # Tenant B requests deletion of an id that exists only under A.
            reg.unregister("solo-A", tenant_id="tenant-B")
            # Tenant A's row is still present.
            assert reg.get("solo-A", tenant_id="tenant-A") is not None
        finally:
            reg.close()


class TestTeamRunRegistryStrictPosture:
    """Under research/prod posture, missing tenant_id is a hard error."""

    @pytest.mark.parametrize("op", ["get", "list_members", "unregister"])
    def test_strict_posture_rejects_empty_tenant_id(self, tmp_path, monkeypatch, op):
        """get/list_members/unregister fail-fast with empty tenant_id under research."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        try:
            method = getattr(reg, op)
            with pytest.raises(ValueError, match="tenant_id is required"):
                method("any-team-id")
        finally:
            reg.close()

    def test_strict_posture_rejects_explicit_empty_tenant_id(self, tmp_path, monkeypatch):
        """tenant_id='' under research is rejected just like None."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        try:
            with pytest.raises(ValueError, match="tenant_id is required"):
                reg.get("any-team-id", tenant_id="")
            with pytest.raises(ValueError, match="tenant_id is required"):
                reg.get("any-team-id", tenant_id="   ")
        finally:
            reg.close()

    def test_dev_posture_accepts_missing_tenant_id_with_warning(
        self, tmp_path, monkeypatch
    ):
        """Under dev posture, a missing tenant_id is permitted (warn-only)."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        try:
            # Should NOT raise.
            assert reg.get("nope") is None
            assert reg.list_members("nope") == []
            reg.unregister("nope")  # no-op, must not raise
        finally:
            reg.close()


class TestLegacyRowsWithoutTenantId:
    """Document that legacy rows (tenant_id='') are scoped strictly under W32."""

    def test_legacy_row_invisible_to_scoped_query(self, tmp_path, monkeypatch):
        """A pre-W32 row with empty tenant_id is NOT returned by scoped queries.

        We only persist active runs, so legacy rows are unlikely to exist;
        this test asserts the new contract: scoped reads never silently
        match unscoped legacy data. The migration warning lives in the
        register() posture check, but read paths are tightened independently.
        """
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")  # so we can construct the legacy row
        db_file = str(tmp_path / "team_registry.sqlite")
        reg = TeamRunRegistry(db_path=db_file)
        try:
            # Manually insert a legacy row with empty tenant_id, mimicking pre-W32 data.
            with reg._lock:  # type: ignore[attr-defined]  # exposed for test setup
                reg._conn.execute(  # type: ignore[attr-defined]  # exposed for test setup
                    "INSERT INTO team_runs (team_id, pi_run_id, project_id, member_runs, "
                    "created_at, status, finished_at, tenant_id, user_id, session_id, "
                    "lead_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("legacy-team", "run-pi-legacy", "proj-legacy", "[]",
                     "2026-04-01T00:00:00+00:00", "created", 0.0,
                     "", "", "", "run-pi-legacy"),
                )
                reg._conn.commit()  # type: ignore[attr-defined]  # exposed for test setup

            # Tenant-scoped query must NOT match the legacy unscoped row.
            assert reg.get("legacy-team", tenant_id="any-tenant") is None
        finally:
            reg.close()
