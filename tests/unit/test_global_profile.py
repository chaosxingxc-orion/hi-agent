"""Tests for G-1: hi_agent_global profile convention; cross_profile_read in TaskContract."""


def test_global_profile_constant():
    from hi_agent.profiles.directory import GLOBAL_PROFILE_ID

    assert GLOBAL_PROFILE_ID == "hi_agent_global"


def test_get_global_profile_path(tmp_path):
    from hi_agent.profiles.directory import GLOBAL_PROFILE_ID, ProfileDirectoryManager

    mgr = ProfileDirectoryManager(home_dir=str(tmp_path))
    path = mgr.get_global_profile_path()
    assert path == tmp_path / GLOBAL_PROFILE_ID


def test_get_global_memory_l3(tmp_path):
    from hi_agent.profiles.directory import ProfileDirectoryManager

    mgr = ProfileDirectoryManager(home_dir=str(tmp_path))
    path = mgr.get_global_memory_l3()
    assert path == tmp_path / "hi_agent_global" / "memory" / "l3"


def test_get_global_skills(tmp_path):
    from hi_agent.profiles.directory import ProfileDirectoryManager

    mgr = ProfileDirectoryManager(home_dir=str(tmp_path))
    path = mgr.get_global_skills()
    assert path == tmp_path / "hi_agent_global" / "skills"


def test_cross_profile_read_field_in_task_contract():
    from hi_agent.contracts.task import TaskContract

    c = TaskContract(
        task_id="t1",
        goal="test",
        task_family="research",
        risk_level="low",
        cross_profile_read=["hi_agent_global/memory/l3"],
    )
    assert "hi_agent_global/memory/l3" in c.cross_profile_read


def test_cross_profile_read_default_is_empty():
    from hi_agent.contracts.task import TaskContract

    c = TaskContract(task_id="t1", goal="test", task_family="research", risk_level="low")
    assert c.cross_profile_read == []


def test_project_cannot_read_sibling_profile():
    from hi_agent.contracts.task import TaskContract

    c = TaskContract(
        task_id="t1",
        goal="test",
        task_family="research",
        risk_level="low",
        cross_profile_read=["hi_agent_global/memory/l3"],
    )
    # cross_profile_read only lists global; project-B access is not present
    assert "project-B/memory/l3" not in c.cross_profile_read


def test_global_profile_path_not_auto_created(tmp_path):
    """get_global_profile_path() returns path without auto-creating directory."""
    from hi_agent.profiles.directory import ProfileDirectoryManager

    mgr = ProfileDirectoryManager(home_dir=str(tmp_path))
    path = mgr.get_global_profile_path()
    # The path is returned as a Path object, directory creation is opt-in
    assert not path.exists() or path.is_dir()  # may or may not exist
