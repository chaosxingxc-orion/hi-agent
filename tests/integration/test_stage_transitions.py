"""Integration test for stage transition legality."""

import pytest
from hi_agent.contracts import StageState
from hi_agent.runtime_adapter.errors import IllegalStateTransitionError

from tests.helpers.kernel_adapter_fixture import MockKernel


def test_legal_stage_transition_path() -> None:
    """PENDING -> ACTIVE -> COMPLETED should be accepted."""
    kernel = MockKernel(strict_mode=True)
    kernel.open_stage("run-1", "S1_understand")

    kernel.mark_stage_state("run-1", "S1_understand", StageState.ACTIVE)
    kernel.mark_stage_state("run-1", "S1_understand", StageState.COMPLETED)

    kernel.assert_stage_state("S1_understand", StageState.COMPLETED)


def test_illegal_stage_transition_rejected() -> None:
    """PENDING -> COMPLETED should be rejected in strict mode."""
    kernel = MockKernel(strict_mode=True)
    kernel.open_stage("run-1", "S2_gather")

    with pytest.raises(IllegalStateTransitionError):
        kernel.mark_stage_state("run-1", "S2_gather", StageState.COMPLETED)

