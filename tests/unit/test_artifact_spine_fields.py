"""Unit tests: Artifact spine fields (tenant_id, user_id, session_id, team_space_id).

CO-5: verifies that all four spine fields exist, default to empty string,
are settable, serialize via to_dict(), and restore via from_dict().
"""

from __future__ import annotations

from hi_agent.artifacts.contracts import Artifact


def test_artifact_has_tenant_id_field() -> None:
    """Artifact must expose tenant_id with default empty string."""
    a = Artifact()
    assert hasattr(a, "tenant_id")
    assert a.tenant_id == ""


def test_artifact_has_user_id_field() -> None:
    """Artifact must expose user_id with default empty string."""
    a = Artifact()
    assert hasattr(a, "user_id")
    assert a.user_id == ""


def test_artifact_has_session_id_field() -> None:
    """Artifact must expose session_id with default empty string."""
    a = Artifact()
    assert hasattr(a, "session_id")
    assert a.session_id == ""


def test_artifact_has_team_space_id_field() -> None:
    """Artifact must expose team_space_id with default empty string."""
    a = Artifact()
    assert hasattr(a, "team_space_id")
    assert a.team_space_id == ""


def test_artifact_spine_fields_settable() -> None:
    """All spine fields must be settable at construction."""
    a = Artifact(
        tenant_id="tenant-x",
        user_id="user-y",
        session_id="sess-z",
        team_space_id="team-w",
    )
    assert a.tenant_id == "tenant-x"
    assert a.user_id == "user-y"
    assert a.session_id == "sess-z"
    assert a.team_space_id == "team-w"


def test_artifact_spine_fields_in_to_dict() -> None:
    """to_dict() must include all four spine fields."""
    a = Artifact(tenant_id="t1", user_id="u1", session_id="s1", team_space_id="ts1")
    d = a.to_dict()
    assert d["tenant_id"] == "t1"
    assert d["user_id"] == "u1"
    assert d["session_id"] == "s1"
    assert d["team_space_id"] == "ts1"


def test_artifact_spine_fields_roundtrip_from_dict() -> None:
    """from_dict() must restore all four spine fields."""
    data = {
        "artifact_id": "abc123",
        "artifact_type": "base",
        "tenant_id": "tenant-a",
        "user_id": "user-b",
        "session_id": "sess-c",
        "team_space_id": "team-d",
    }
    a = Artifact.from_dict(data)
    assert a.tenant_id == "tenant-a"
    assert a.user_id == "user-b"
    assert a.session_id == "sess-c"
    assert a.team_space_id == "team-d"


def test_artifact_from_dict_ignores_unknown_keys() -> None:
    """from_dict() must silently ignore keys not in the dataclass."""
    data = {
        "artifact_id": "xyz",
        "tenant_id": "t1",
        "unknown_future_field": "should-be-ignored",
    }
    a = Artifact.from_dict(data)
    assert a.tenant_id == "t1"


def test_artifact_backward_compat_no_spine_fields() -> None:
    """from_dict() with no spine fields must default them to empty string."""
    data = {"artifact_id": "old-style", "artifact_type": "base"}
    a = Artifact.from_dict(data)
    assert a.tenant_id == ""
    assert a.user_id == ""
    assert a.session_id == ""
    assert a.team_space_id == ""
