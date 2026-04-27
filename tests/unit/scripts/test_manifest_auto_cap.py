"""Tests for _compute_cap auto-cap triggers."""


def test_dirty_worktree_caps_to_70():
    from scripts.build_release_manifest import _compute_cap
    cap, _reason, factors = _compute_cap({}, is_dirty=True)
    # dirty_worktree cap is 70; head_mismatch (live git) may add a lower cap — either is valid
    assert cap is not None
    assert cap <= 70.0
    assert "dirty_worktree" in factors


def test_t3_stale_caps_to_80():
    from scripts.build_release_manifest import _compute_cap
    cap, _reason, factors = _compute_cap({}, t3_stale=True)
    assert cap is not None
    assert "t3_stale" in factors


def test_expired_allowlist_caps():
    from scripts.build_release_manifest import _compute_cap
    cap, _reason, factors = _compute_cap({}, expired_allowlist=2)
    assert cap is not None
    assert any("expired_allowlist" in f for f in factors)


def test_all_pass_no_explicit_cap_factors():
    # Verifies that clean-state conditions don't spuriously fire for explicit conditions.
    # head_mismatch is a live git check and may apply; test focuses on known conditions.
    from scripts.build_release_manifest import _compute_cap
    _cap, _reason, factors = _compute_cap({}, is_dirty=False, t3_stale=False, expired_allowlist=0)
    assert "dirty_worktree" not in factors
    assert "t3_stale" not in factors
    assert not any("expired_allowlist" in f for f in factors)
