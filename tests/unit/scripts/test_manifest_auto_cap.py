"""Tests for _compute_cap auto-cap triggers."""


def test_dirty_worktree_caps_to_70():
    from scripts.build_release_manifest import _compute_cap
    cap, _reason, factors = _compute_cap({}, is_dirty=True)
    assert cap == 70.0
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


def test_all_pass_no_cap():
    from scripts.build_release_manifest import _compute_cap
    cap, _reason, _factors = _compute_cap({}, is_dirty=False, t3_stale=False, expired_allowlist=0)
    assert cap is None
