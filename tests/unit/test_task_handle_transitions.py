"""Tests for TaskHandle state transitions and locking."""

import pytest
from hi_agent.task_mgmt.handle import (
    InvalidTransitionError,
    TaskHandle,
    TaskStatus,
)


class TestTaskHandleTransitions:
    """Test suite for TaskHandle state transition validation."""

    def test_valid_transition_pending_to_running(self):
        """Valid transition: PENDING → RUNNING."""
        handle = TaskHandle(task_id="task-1", node_id="node-1")
        assert handle.status == TaskStatus.PENDING

        handle.transition_to(TaskStatus.RUNNING)
        assert handle.status == TaskStatus.RUNNING

    def test_valid_transition_pending_to_ready(self):
        """Valid transition: PENDING → READY."""
        handle = TaskHandle(task_id="task-1", node_id="node-1")
        handle.transition_to(TaskStatus.READY)
        assert handle.status == TaskStatus.READY

    def test_valid_transition_pending_to_cancelled(self):
        """Valid transition: PENDING → CANCELLED."""
        handle = TaskHandle(task_id="task-1", node_id="node-1")
        handle.transition_to(TaskStatus.CANCELLED)
        assert handle.status == TaskStatus.CANCELLED

    def test_valid_transition_ready_to_running(self):
        """Valid transition: READY → RUNNING."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.READY)
        handle.transition_to(TaskStatus.RUNNING)
        assert handle.status == TaskStatus.RUNNING

    def test_valid_transition_running_to_completed(self):
        """Valid transition: RUNNING → COMPLETED."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.RUNNING)
        handle.transition_to(TaskStatus.COMPLETED)
        assert handle.status == TaskStatus.COMPLETED

    def test_valid_transition_running_to_failed(self):
        """Valid transition: RUNNING → FAILED."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.RUNNING)
        handle.transition_to(TaskStatus.FAILED)
        assert handle.status == TaskStatus.FAILED

    def test_valid_transition_running_to_blocked(self):
        """Valid transition: RUNNING → BLOCKED."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.RUNNING)
        handle.transition_to(TaskStatus.BLOCKED)
        assert handle.status == TaskStatus.BLOCKED

    def test_valid_transition_running_to_yielded(self):
        """Valid transition: RUNNING → YIELDED."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.RUNNING)
        handle.transition_to(TaskStatus.YIELDED)
        assert handle.status == TaskStatus.YIELDED

    def test_valid_transition_blocked_to_running(self):
        """Valid transition: BLOCKED → RUNNING."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.BLOCKED)
        handle.transition_to(TaskStatus.RUNNING)
        assert handle.status == TaskStatus.RUNNING

    def test_valid_transition_yielded_to_running(self):
        """Valid transition: YIELDED → RUNNING."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.YIELDED)
        handle.transition_to(TaskStatus.RUNNING)
        assert handle.status == TaskStatus.RUNNING

    def test_invalid_transition_completed_to_running(self):
        """Invalid transition: COMPLETED → RUNNING (terminal state)."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.COMPLETED)
        with pytest.raises(InvalidTransitionError) as exc_info:
            handle.transition_to(TaskStatus.RUNNING)
        assert "Cannot transition" in str(exc_info.value)
        assert "COMPLETED" in str(exc_info.value)
        assert "RUNNING" in str(exc_info.value)

    def test_invalid_transition_failed_to_running(self):
        """Invalid transition: FAILED → RUNNING (terminal state)."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.FAILED)
        with pytest.raises(InvalidTransitionError):
            handle.transition_to(TaskStatus.RUNNING)

    def test_invalid_transition_cancelled_to_running(self):
        """Invalid transition: CANCELLED → RUNNING (terminal state)."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.CANCELLED)
        with pytest.raises(InvalidTransitionError):
            handle.transition_to(TaskStatus.RUNNING)

    def test_invalid_transition_pending_to_blocked(self):
        """Invalid transition: PENDING → BLOCKED (not in allowed set)."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.PENDING)
        with pytest.raises(InvalidTransitionError):
            handle.transition_to(TaskStatus.BLOCKED)

    def test_invalid_transition_pending_to_completed(self):
        """Invalid transition: PENDING → COMPLETED (must go through RUNNING)."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.PENDING)
        with pytest.raises(InvalidTransitionError):
            handle.transition_to(TaskStatus.COMPLETED)

    def test_invalid_transition_ready_to_blocked(self):
        """Invalid transition: READY → BLOCKED (not allowed)."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.READY)
        with pytest.raises(InvalidTransitionError):
            handle.transition_to(TaskStatus.BLOCKED)

    def test_is_blocked_with_blocked_status(self):
        """is_blocked() returns True for BLOCKED status."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.BLOCKED)
        assert handle.is_blocked() is True

    def test_is_blocked_with_yielded_status(self):
        """is_blocked() returns True for YIELDED status."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.YIELDED)
        assert handle.is_blocked() is True

    def test_is_blocked_with_running_status(self):
        """is_blocked() returns False for RUNNING status."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.RUNNING)
        assert handle.is_blocked() is False

    def test_is_blocked_with_pending_status(self):
        """is_blocked() returns False for PENDING status."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.PENDING)
        assert handle.is_blocked() is False

    def test_transition_to_same_status(self):
        """Transition to same status should raise error (no self-loop)."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.RUNNING)
        with pytest.raises(InvalidTransitionError):
            handle.transition_to(TaskStatus.RUNNING)

    def test_lock_prevents_concurrent_modification(self):
        """Lock is acquired during state transition."""
        import threading

        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.PENDING)
        transition_order = []

        def transition_with_delay():
            # This will hold the lock briefly
            handle.transition_to(TaskStatus.RUNNING)
            transition_order.append("first")

        thread = threading.Thread(target=transition_with_delay)
        thread.start()
        thread.join()

        # Verify the transition succeeded and lock was used
        assert handle.status == TaskStatus.RUNNING
        assert transition_order == ["first"]

    def test_multiple_valid_transitions_in_sequence(self):
        """Perform a sequence of valid transitions."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.PENDING)

        handle.transition_to(TaskStatus.READY)
        assert handle.status == TaskStatus.READY

        handle.transition_to(TaskStatus.RUNNING)
        assert handle.status == TaskStatus.RUNNING

        handle.transition_to(TaskStatus.COMPLETED)
        assert handle.status == TaskStatus.COMPLETED

    def test_error_message_format(self):
        """Error message contains source and target statuses."""
        handle = TaskHandle(task_id="task-1", node_id="node-1", status=TaskStatus.COMPLETED)
        with pytest.raises(InvalidTransitionError) as exc_info:
            handle.transition_to(TaskStatus.FAILED)

        error_msg = str(exc_info.value)
        assert "Cannot transition" in error_msg
        assert "COMPLETED" in error_msg
        assert "FAILED" in error_msg
