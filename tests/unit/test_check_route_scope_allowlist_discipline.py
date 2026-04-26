"""Tests for AllowlistEntry validation in check_route_scope.py."""
import importlib.util
from pathlib import Path

import pytest


def _import_module():
    import sys as _sys

    mod_name = "check_route_scope"
    spec = importlib.util.spec_from_file_location(
        mod_name, Path("scripts/check_route_scope.py")
    )
    if spec is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        return None
    # Register in sys.modules so dataclass string-annotation resolution works
    _sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del _sys.modules[mod_name]
        raise
    return mod


def test_allowlist_is_dict():
    """NO_SCOPE_ALLOWLIST must be a dict, not a frozenset."""
    mod = _import_module()
    if mod is None:
        pytest.skip("Cannot import module")
    assert isinstance(mod.NO_SCOPE_ALLOWLIST, dict), (
        f"Expected dict, got {type(mod.NO_SCOPE_ALLOWLIST)}"
    )


def test_all_entries_have_required_fields():
    """Every AllowlistEntry must have non-empty reason, owner, expiry_wave, replacement_test."""
    mod = _import_module()
    if mod is None:
        pytest.skip("Cannot import module")

    for handler_name, entry in mod.NO_SCOPE_ALLOWLIST.items():
        assert entry.reason, f"Entry '{handler_name}' has empty reason"
        assert entry.owner, f"Entry '{handler_name}' has empty owner"
        assert entry.expiry_wave, f"Entry '{handler_name}' has empty expiry_wave"
        assert entry.replacement_test, f"Entry '{handler_name}' has empty replacement_test"


def test_entry_missing_owner_fails_validation():
    """_validate_allowlist() must catch entries with missing owner."""
    mod = _import_module()
    if mod is None or not hasattr(mod, "_validate_allowlist"):
        pytest.skip("Module or _validate_allowlist not available")

    allowlist_entry_cls = mod.AllowlistEntry
    original = dict(mod.NO_SCOPE_ALLOWLIST)
    mod.NO_SCOPE_ALLOWLIST["__test_bad__"] = allowlist_entry_cls(
        reason="test", risk="", owner="", expiry_wave="Wave 11", replacement_test="test.py"
    )
    try:
        issues = mod._validate_allowlist()
        assert any("__test_bad__" in i for i in issues), (
            f"Should report missing owner for __test_bad__; got: {issues}"
        )
    finally:
        mod.NO_SCOPE_ALLOWLIST.clear()
        mod.NO_SCOPE_ALLOWLIST.update(original)


def test_entry_missing_reason_fails_validation():
    """_validate_allowlist() must catch entries with missing reason."""
    mod = _import_module()
    if mod is None or not hasattr(mod, "_validate_allowlist"):
        pytest.skip("Module or _validate_allowlist not available")

    allowlist_entry_cls = mod.AllowlistEntry
    original = dict(mod.NO_SCOPE_ALLOWLIST)
    mod.NO_SCOPE_ALLOWLIST["__test_no_reason__"] = allowlist_entry_cls(
        reason="", risk="", owner="GOV", expiry_wave="permanent", replacement_test="test.py"
    )
    try:
        issues = mod._validate_allowlist()
        assert any("__test_no_reason__" in i for i in issues), (
            f"Should report missing reason for __test_no_reason__; got: {issues}"
        )
    finally:
        mod.NO_SCOPE_ALLOWLIST.clear()
        mod.NO_SCOPE_ALLOWLIST.update(original)


def test_validate_allowlist_returns_empty_for_valid_entries():
    """_validate_allowlist() must return empty list when all entries are valid."""
    mod = _import_module()
    if mod is None or not hasattr(mod, "_validate_allowlist"):
        pytest.skip("Module or _validate_allowlist not available")

    issues = mod._validate_allowlist()
    assert issues == [], f"Expected no issues but got: {issues}"


def test_handler_membership_check_works_with_dict():
    """'handler_name in NO_SCOPE_ALLOWLIST' must work the same as with frozenset."""
    mod = _import_module()
    if mod is None:
        pytest.skip("Cannot import module")

    # Spot-check a few known entries
    assert "handle_health" in mod.NO_SCOPE_ALLOWLIST
    assert "handle_manifest" in mod.NO_SCOPE_ALLOWLIST
    assert "handle_knowledge_ingest" in mod.NO_SCOPE_ALLOWLIST
    assert "__nonexistent_handler__" not in mod.NO_SCOPE_ALLOWLIST


def test_allowlist_entry_is_frozen():
    """AllowlistEntry must be a frozen dataclass (immutable)."""
    mod = _import_module()
    if mod is None:
        pytest.skip("Cannot import module")

    entry = mod.NO_SCOPE_ALLOWLIST["handle_health"]
    with pytest.raises((AttributeError, TypeError)):
        entry.owner = "TAMPERED"  # type: ignore[misc]
