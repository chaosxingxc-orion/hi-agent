"""Unit tests for StageDirective contract — W25-M.1.

Verifies InsertSpec anchor field, skip_to action, and cross-field validators.
"""

import pytest
from hi_agent.contracts.directives import InsertSpec, StageDirective


def test_skip_requires_target_stage_id():
    with pytest.raises(ValueError, match="target_stage_id"):
        StageDirective(action="skip")


def test_skip_to_requires_skip_to_field():
    with pytest.raises(ValueError, match="skip_to"):
        StageDirective(action="skip_to")


def test_insert_requires_insert_list():
    with pytest.raises(ValueError, match="at least one InsertSpec"):
        StageDirective(action="insert")


def test_valid_skip_to():
    d = StageDirective(action="skip_to", skip_to="stage-3")
    assert d.skip_to == "stage-3"


def test_valid_insert_with_anchor():
    spec = InsertSpec(target_stage_id="stage-2", new_stage="stage-injected", config={"k": "v"})
    d = StageDirective(action="insert", insert=[spec])
    assert d.insert[0].target_stage_id == "stage-2"
    assert d.insert[0].new_stage == "stage-injected"


def test_valid_repeat():
    d = StageDirective(action="repeat", target_stage_id="stage-1")
    assert d.target_stage_id == "stage-1"


def test_valid_skip():
    d = StageDirective(action="skip", target_stage_id="stage-2")
    assert d.target_stage_id == "stage-2"


def test_insert_spec_config_defaults_empty():
    spec = InsertSpec(target_stage_id="s1", new_stage="s-new")
    assert spec.config == {}
