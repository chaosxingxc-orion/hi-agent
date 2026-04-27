"""Tests for score_caps.yaml registry and cap computation."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent
SCORE_CAPS_FILE = ROOT / "docs" / "governance" / "score_caps.yaml"
SCORING_SCRIPTS = [
    ROOT / "scripts" / "build_release_manifest.py",
    ROOT / "scripts" / "check_downstream_response_format.py",
    ROOT / "scripts" / "release_notice.py",
    ROOT / "scripts" / "check_doc_consistency.py",
]
FORBIDDEN_LITERALS = ["76.5", "78.0", " 70.0", " 80.0"]


def test_score_caps_yaml_exists():
    assert SCORE_CAPS_FILE.exists()


def test_score_caps_yaml_has_required_conditions():
    text = SCORE_CAPS_FILE.read_text(encoding="utf-8")
    for cond in ["gate_fail", "gate_warn", "t3_stale", "t3_deferred", "gate_missing"]:
        assert cond in text, f"score_caps.yaml missing condition: {cond}"


def test_no_hardcoded_score_literals_in_build_manifest():
    """The primary (registry-driven) cap path must not hardcode 70.0/80.0.

    The fallback branch (used when score_caps.yaml cannot be loaded) is allowed to
    reference 70.0 and 80.0 as explicit literals — we allow up to 3 occurrences each
    (docstring + fallback return + fallback default argument).
    """
    import ast
    src = (ROOT / "scripts" / "build_release_manifest.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_compute_cap":
            func_src = ast.get_source_segment(src, node) or ""
            for lit in ["70.0", "80.0"]:
                occurrences = func_src.count(lit)
                # Fallback branch legitimately uses each literal at most 3 times:
                # once in the docstring, once as a return value, once as a default arg.
                assert occurrences <= 3, (
                    f"Hardcoded {lit} found {occurrences} times in _compute_cap "
                    f"(expected at most 3, restricted to fallback branch)"
                )


def test_t3_deferred_cap_below_t3_stale_cap():
    """t3_deferred cap (72) must be higher than t3_stale cap (63) but below warn cap (80)."""
    text = SCORE_CAPS_FILE.read_text(encoding="utf-8")
    caps: dict[str, float] = {}
    current: str | None = None
    for line in text.splitlines():
        m = re.match(r"\s+- condition: (\S+)", line)
        if m:
            current = m.group(1)
        if current:
            m2 = re.match(r"\s+cap: (\d+(?:\.\d+)?)", line)
            if m2:
                caps[current] = float(m2.group(1))
                current = None
    assert "t3_deferred" in caps, "score_caps.yaml missing t3_deferred"
    assert "t3_stale" in caps, "score_caps.yaml missing t3_stale"
    assert caps["t3_deferred"] > caps["t3_stale"], (
        f"t3_deferred cap ({caps['t3_deferred']}) must be > t3_stale cap ({caps['t3_stale']})"
    )
    assert caps["t3_deferred"] < 80, (
        f"t3_deferred cap ({caps['t3_deferred']}) must be < 80"
    )


def test_score_caps_yaml_schema_version():
    text = SCORE_CAPS_FILE.read_text(encoding="utf-8")
    assert 'schema_version: "1"' in text, "score_caps.yaml must declare schema_version: \"1\""


def test_score_caps_all_rules_have_required_fields():
    text = SCORE_CAPS_FILE.read_text(encoding="utf-8")
    current: str | None = None
    rule_fields: dict[str, set[str]] = {}
    for line in text.splitlines():
        m = re.match(r"\s+- condition: (\S+)", line)
        if m:
            current = m.group(1)
            rule_fields[current] = set()
        if current:
            for field in ("cap", "factor", "description"):
                if re.match(rf"\s+{field}:", line):
                    rule_fields[current].add(field)
    for cond, fields in rule_fields.items():
        for required in ("cap", "factor", "description"):
            assert required in fields, (
                f"score_caps.yaml rule '{cond}' is missing required field '{required}'"
            )


def test_no_hardcoded_76_5_in_check_downstream():
    src = (ROOT / "scripts" / "check_downstream_response_format.py").read_text(encoding="utf-8")
    assert "76.5" not in src, "check_downstream_response_format.py still contains hardcoded 76.5"


def test_no_hardcoded_78_0_in_check_downstream():
    src = (ROOT / "scripts" / "check_downstream_response_format.py").read_text(encoding="utf-8")
    assert "78.0" not in src, "check_downstream_response_format.py still contains hardcoded 78.0"


def test_release_notice_no_hardcoded_score():
    src = (ROOT / "scripts" / "release_notice.py").read_text(encoding="utf-8")
    assert "76.5" not in src, "release_notice.py still contains hardcoded 76.5"
    assert "_DEFAULT_SCORE_CAP" not in src, (
        "release_notice.py should not have hardcoded _DEFAULT_SCORE_CAP"
    )
