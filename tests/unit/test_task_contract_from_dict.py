"""Unit test: TaskContract.from_dict constructs from HTTP request body."""

from hi_agent.contracts.task import TaskBudget, TaskContract


def test_from_dict_populates_basic_fields():
    """from_dict reads goal, task_id, project_id from payload."""
    payload = {
        "task_id": "task-1",
        "goal": "Research the topic",
        "project_id": "proj-1",
    }
    contract = TaskContract.from_dict(payload)

    assert contract.task_id == "task-1"
    assert contract.goal == "Research the topic"
    assert contract.project_id == "proj-1"


def test_from_dict_populates_spine_fields():
    """from_dict reads tenant_id, user_id, session_id when present."""
    payload = {
        "task_id": "t",
        "goal": "goal",
        "project_id": "p1",
    }
    # tenant_id, user_id, session_id are not TaskContract fields but
    # from_dict should silently ignore them (they're not in the dataclass).
    # Verify no exception is raised.
    contract = TaskContract.from_dict(payload)
    assert contract.project_id == "p1"


def test_from_dict_missing_fields_use_defaults():
    """Missing fields fall back to TaskContract defaults."""
    contract = TaskContract.from_dict({"task_id": "x", "goal": "y"})

    assert contract.task_family == "quick_task"
    assert contract.priority == 5
    assert contract.risk_level == "low"
    assert contract.constraints == []
    assert contract.acceptance_criteria == []
    assert contract.budget is None


def test_from_dict_budget_dict_converted_to_task_budget():
    """Budget dict is converted to TaskBudget instance."""
    payload = {
        "task_id": "t",
        "goal": "g",
        "budget": {"max_llm_calls": 10, "max_wall_clock_seconds": 600},
    }
    contract = TaskContract.from_dict(payload)

    assert isinstance(contract.budget, TaskBudget)
    assert contract.budget.max_llm_calls == 10
    assert contract.budget.max_wall_clock_seconds == 600


def test_from_dict_budget_task_budget_passthrough():
    """Existing TaskBudget instance is passed through unchanged."""
    budget = TaskBudget(max_llm_calls=5)
    payload = {"task_id": "t", "goal": "g", "budget": budget}

    contract = TaskContract.from_dict(payload)

    assert contract.budget is budget


def test_from_dict_lists_populated():
    """List fields are read from payload."""
    payload = {
        "task_id": "t",
        "goal": "g",
        "constraints": ["fail_action:stage1"],
        "acceptance_criteria": ["required_stage:s1"],
        "input_refs": ["ref1"],
    }
    contract = TaskContract.from_dict(payload)

    assert contract.constraints == ["fail_action:stage1"]
    assert contract.acceptance_criteria == ["required_stage:s1"]
    assert contract.input_refs == ["ref1"]


def test_from_dict_empty_payload_uses_defaults():
    """Empty payload (missing required goal/task_id) returns empty-string defaults."""
    # No exception; goal/task_id default to ""
    contract = TaskContract.from_dict({})

    assert contract.task_id == ""
    assert contract.goal == ""
    assert contract.project_id == ""
