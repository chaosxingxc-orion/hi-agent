"""Tests for RunFinalizer opt-in team sync via share_to_team flag."""

from unittest.mock import MagicMock


def _make_finalizer(team_space=None, share_to_team=False):
    """Build a RunFinalizer with minimal real dependencies for team-sync tests."""
    from hi_agent.execution.run_finalizer import RunFinalizer, RunFinalizerContext

    contract = MagicMock()
    contract.acceptance_criteria = []

    lifecycle = MagicMock()
    lifecycle.finalize_run.return_value = None

    kernel = MagicMock()
    kernel.mode = "test"

    ctx = RunFinalizerContext(
        run_id="test-run-001",
        contract=contract,
        lifecycle=lifecycle,
        kernel=kernel,
    )

    return RunFinalizer(ctx, team_space=team_space, share_to_team=share_to_team)


def test_finalizer_does_not_sync_when_share_to_team_false():
    """Default: no team sync on run completion when share_to_team is False."""
    team_space = MagicMock()
    finalizer = _make_finalizer(team_space=team_space, share_to_team=False)
    finalizer.finalize("completed")
    team_space.publish.assert_not_called()


def test_finalizer_does_not_sync_when_team_space_is_none():
    """No sync when team_space is None even if share_to_team=True."""
    finalizer = _make_finalizer(team_space=None, share_to_team=True)
    # Should not raise
    finalizer.finalize("completed")


def test_finalizer_syncs_when_share_to_team_true():
    """Opt-in: team sync fires when share_to_team=True and team_space is set."""
    team_space = MagicMock()
    finalizer = _make_finalizer(team_space=team_space, share_to_team=True)
    finalizer.finalize("completed")
    team_space.publish.assert_called_once()
    call_kwargs = team_space.publish.call_args
    assert call_kwargs.kwargs.get("publish_reason") == "auto_sync"


def test_finalizer_syncs_correct_event_type():
    """Team sync publishes event_type='run_summary'."""
    team_space = MagicMock()
    finalizer = _make_finalizer(team_space=team_space, share_to_team=True)
    finalizer.finalize("completed")
    call_kwargs = team_space.publish.call_args
    assert call_kwargs.kwargs.get("event_type") == "run_summary"


def test_finalizer_syncs_run_id():
    """Team sync passes the correct source_run_id."""
    team_space = MagicMock()
    finalizer = _make_finalizer(team_space=team_space, share_to_team=True)
    finalizer.finalize("completed")
    call_kwargs = team_space.publish.call_args
    assert call_kwargs.kwargs.get("source_run_id") == "test-run-001"


def test_finalizer_syncs_outcome_in_payload():
    """Team sync payload contains the outcome."""
    team_space = MagicMock()
    finalizer = _make_finalizer(team_space=team_space, share_to_team=True)
    finalizer.finalize("completed")
    call_kwargs = team_space.publish.call_args
    payload = call_kwargs.kwargs.get("payload", {})
    assert payload.get("outcome") == "completed"


def test_finalizer_syncs_on_failed_outcome():
    """Team sync also fires for non-completed outcomes."""
    team_space = MagicMock()
    finalizer = _make_finalizer(team_space=team_space, share_to_team=True)
    finalizer.finalize("failed")
    team_space.publish.assert_called_once()
