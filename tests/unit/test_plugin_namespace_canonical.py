"""Test that hi_agent.plugins is the canonical namespace.

hi_agent.plugin (singular) must emit a DeprecationWarning but still work.
"""
from __future__ import annotations

import warnings


def test_canonical_import_works():
    """hi_agent.plugins.PluginManifest imports without warning."""
    import hi_agent.plugins.manifest  # noqa: F401  expiry_wave: Wave 29
    # No DeprecationWarning


def test_deprecated_import_warns():
    """hi_agent.plugin (singular) emits DeprecationWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import hi_agent.plugin  # noqa: F401  expiry_wave: Wave 29
    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecation_warnings, "Expected DeprecationWarning from hi_agent.plugin import"
    assert "hi_agent.plugins" in str(deprecation_warnings[0].message)
