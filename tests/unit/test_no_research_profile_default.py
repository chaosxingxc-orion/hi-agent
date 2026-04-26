"""Test that platform config does not hardcode 'research' as a profile default."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def test_json_config_loader_no_research_default():
    loader = ROOT / "hi_agent" / "config" / "json_config_loader.py"
    if not loader.exists():
        return
    src = loader.read_text(encoding="utf-8")
    matches = re.findall(r'profile_id\s*[=:]\s*["\']research["\']', src)
    assert not matches, f"Hardcoded profile_id='research' found: {matches}"


def test_cognition_builder_no_research_defaults_function():
    cb = ROOT / "hi_agent" / "config" / "cognition_builder.py"
    if not cb.exists():
        return
    src = cb.read_text(encoding="utf-8")
    import ast
    tree = ast.parse(src)
    func_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert "apply_research_defaults" not in func_names, (
        "cognition_builder.py defines apply_research_defaults — "
        "rename to apply_strict_defaults"
    )
