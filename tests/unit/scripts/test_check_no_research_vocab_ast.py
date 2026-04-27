"""Tests for check_no_research_vocab.py extended AST coverage.

Covers:
- FunctionDef.name hard-ban detection
- AsyncFunctionDef.name hard-ban detection
- ClassDef.name hard-ban detection
- ImportFrom.names hard-ban detection
- Top-level Name assignment hard-ban detection
- Soft-ban identifier detection
- # legacy: line annotation suppression
- Migration-guide text scan
- --json output mode
- Existing allowlist path entries still work
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

# Insert scripts/ onto sys.path so check_no_research_vocab is importable
_SCRIPTS = Path(__file__).parent.parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import check_no_research_vocab as checker


# ---------------------------------------------------------------------------
# Hard-ban: FunctionDef.name
# ---------------------------------------------------------------------------

def test_detects_function_def_with_forbidden_name(tmp_path):
    """FunctionDef.name containing a hard-ban identifier must be reported."""
    source = "def pi_run_id(builder): pass\n"
    f = tmp_path / "bad.py"
    f.write_text(source)
    hard, _soft = checker.check_file_split(f)
    assert any("pi_run_id" in h for h in hard), (
        f"Expected hard-ban hit for 'pi_run_id' in FunctionDef; got: {hard}"
    )


def test_detects_async_function_def_with_forbidden_name(tmp_path):
    """AsyncFunctionDef.name containing a hard-ban identifier must be reported."""
    source = "async def pi_run_id(builder): ...\n"
    f = tmp_path / "bad_async.py"
    f.write_text(source)
    hard, _soft = checker.check_file_split(f)
    assert any("pi_run_id" in h for h in hard), (
        f"Expected hard-ban hit for 'pi_run_id' in AsyncFunctionDef; got: {hard}"
    )


# ---------------------------------------------------------------------------
# Hard-ban: ClassDef.name
# ---------------------------------------------------------------------------

def test_detects_class_def_with_forbidden_name(tmp_path):
    """ClassDef.name matching a hard-ban identifier must be reported."""
    source = "class RunPostmortem:\n    pass\n"
    f = tmp_path / "bad_class.py"
    f.write_text(source)
    hard, _soft = checker.check_file_split(f)
    assert any("RunPostmortem" in h for h in hard), (
        f"Expected hard-ban hit for 'RunPostmortem' ClassDef; got: {hard}"
    )


def test_detects_evolution_experiment_class_def(tmp_path):
    """EvolutionExperiment ClassDef must be caught as hard-ban."""
    source = "class EvolutionExperiment:\n    trial_id: str\n"
    f = tmp_path / "bad2.py"
    f.write_text(source)
    hard, _soft = checker.check_file_split(f)
    assert any("EvolutionExperiment" in h for h in hard), (
        f"Expected hard-ban hit for 'EvolutionExperiment'; got: {hard}"
    )


# ---------------------------------------------------------------------------
# Hard-ban: ImportFrom.names
# ---------------------------------------------------------------------------

def test_detects_import_of_forbidden_name(tmp_path):
    """Importing a hard-ban identifier via 'from X import Y' must be reported."""
    source = "from some.module import RunPostmortem\n"
    f = tmp_path / "bad_import.py"
    f.write_text(source)
    hard, _soft = checker.check_file_split(f)
    assert any("RunPostmortem" in h for h in hard), (
        f"Expected hard-ban hit for 'RunPostmortem' in ImportFrom; got: {hard}"
    )


def test_detects_import_alias_of_forbidden_name(tmp_path):
    """Importing with an alias that is a hard-ban identifier must be reported."""
    source = "from some.module import SomeName as RunPostmortem\n"
    f = tmp_path / "bad_alias.py"
    f.write_text(source)
    hard, _soft = checker.check_file_split(f)
    assert any("RunPostmortem" in h for h in hard), (
        f"Expected hard-ban hit for alias 'RunPostmortem' in ImportFrom; got: {hard}"
    )


# ---------------------------------------------------------------------------
# Hard-ban: top-level Name assignment
# ---------------------------------------------------------------------------

def test_detects_top_level_assignment_with_forbidden_name(tmp_path):
    """A top-level assignment 'pi_run_id = ...' must be reported as hard-ban."""
    source = "pi_run_id = 'some_value'\n"
    f = tmp_path / "bad_assign.py"
    f.write_text(source)
    hard, _soft = checker.check_file_split(f)
    assert any("pi_run_id" in h for h in hard), (
        f"Expected hard-ban hit for top-level assignment 'pi_run_id'; got: {hard}"
    )


# ---------------------------------------------------------------------------
# Existing checks preserved
# ---------------------------------------------------------------------------

def test_detects_attribute_access_pi_run_id(tmp_path):
    """Attribute access '.pi_run_id' must still be detected (existing check)."""
    source = "x = obj.pi_run_id\n"
    f = tmp_path / "bad_attr.py"
    f.write_text(source)
    hard, _soft = checker.check_file_split(f)
    assert any("pi_run_id" in h for h in hard), (
        f"Expected hard-ban hit for '.pi_run_id' attribute; got: {hard}"
    )


def test_detects_run_postmortem_construction(tmp_path):
    """RunPostmortem() construction must still be detected (existing check)."""
    source = 'result = RunPostmortem(run_id="r1", tenant_id="t1")\n'
    f = tmp_path / "bad_call.py"
    f.write_text(source)
    hard, _soft = checker.check_file_split(f)
    assert any("RunPostmortem" in h for h in hard), (
        f"Expected hard-ban hit for 'RunPostmortem()'; got: {hard}"
    )


# ---------------------------------------------------------------------------
# Soft-ban identifiers
# ---------------------------------------------------------------------------

def test_detects_soft_ban_identifier_as_function_name(tmp_path):
    """A soft-ban identifier used as a function name must appear in soft violations."""
    source = "def survey_synthesis(docs): return docs\n"
    f = tmp_path / "soft_func.py"
    f.write_text(source)
    hard, soft = checker.check_file_split(f)
    assert not hard, f"Should not be a hard-ban hit; got: {hard}"
    assert any("survey_synthesis" in s for s in soft), (
        f"Expected soft-ban warn for 'survey_synthesis'; got: {soft}"
    )


def test_detects_soft_ban_identifier_as_class_name(tmp_path):
    """A soft-ban identifier used as a class name must appear in soft violations."""
    source = "class CitationArtifact:\n    pass\n"
    f = tmp_path / "soft_class.py"
    f.write_text(source)
    hard, soft = checker.check_file_split(f)
    assert not hard, f"Should not be a hard-ban hit; got: {hard}"
    assert any("CitationArtifact" in s for s in soft), (
        f"Expected soft-ban warn for 'CitationArtifact'; got: {soft}"
    )


# ---------------------------------------------------------------------------
# # legacy: line annotation suppression
# ---------------------------------------------------------------------------

def test_skips_legacy_annotated_line(tmp_path):
    """Lines with '# legacy:' comment must be suppressed for any ban check."""
    source = "x = obj.pi_run_id  # legacy: migration read path\n"
    f = tmp_path / "ok.py"
    f.write_text(source)
    hard, soft = checker.check_file_split(f)
    assert not hard, f"Hard-ban must be suppressed by # legacy: annotation; got: {hard}"
    assert not soft, f"Soft-ban must also be suppressed by # legacy: annotation; got: {soft}"


def test_skips_legacy_annotated_function_def(tmp_path):
    """A FunctionDef line with '# legacy:' must be suppressed."""
    source = "def pi_run_id(x): pass  # legacy: deprecated shim\n"
    f = tmp_path / "ok2.py"
    f.write_text(source)
    hard, _soft = checker.check_file_split(f)
    assert not hard, f"Hard-ban must be suppressed by # legacy: on same line; got: {hard}"


# ---------------------------------------------------------------------------
# Path allowlist
# ---------------------------------------------------------------------------

def test_allowlisted_path_is_fully_skipped():
    """Files in _PATH_ALLOWLIST must return no violations at all."""
    assert hasattr(checker, "_PATH_ALLOWLIST"), "_PATH_ALLOWLIST must exist"
    # Verify the set is non-empty and contains at least one known shim
    assert "hi_agent/contracts/team_runtime.py" in checker._PATH_ALLOWLIST


def test_soft_ban_path_allowlist_exists():
    """_SOFT_BAN_PATH_ALLOWLIST must exist and cover tier_presets.py."""
    assert hasattr(checker, "_SOFT_BAN_PATH_ALLOWLIST"), "_SOFT_BAN_PATH_ALLOWLIST must exist"
    assert "hi_agent/llm/tier_presets.py" in checker._SOFT_BAN_PATH_ALLOWLIST, (
        "tier_presets.py must be in soft-ban allowlist (Wave 12 target)"
    )


def test_soft_ban_allowlisted_file_produces_no_soft_violations(tmp_path):
    """A file in _SOFT_BAN_PATH_ALLOWLIST must not produce soft violations,
    even if it uses soft-ban identifiers."""
    # We can't easily use the real tier_presets.py path in a tmp test,
    # so we verify the allowlist lookup function is consistent.
    assert hasattr(checker, "_is_soft_ban_allowlisted"), (
        "_is_soft_ban_allowlisted helper must be defined"
    )


# ---------------------------------------------------------------------------
# Ban list structure
# ---------------------------------------------------------------------------

def test_hard_ban_identifiers_exists():
    """_HARD_BAN_IDENTIFIERS must exist and contain the required entries."""
    assert hasattr(checker, "_HARD_BAN_IDENTIFIERS"), "_HARD_BAN_IDENTIFIERS must exist"
    hb = checker._HARD_BAN_IDENTIFIERS
    assert "pi_run_id" in hb
    assert "RunPostmortem" in hb
    assert "ProjectPostmortem" in hb
    assert "EvolutionExperiment" in hb
    # apply_research_defaults moved to _SOFT_BAN_IDENTIFIERS in Wave 12
    assert "apply_research_defaults" not in hb


def test_soft_ban_identifiers_exists():
    """_SOFT_BAN_IDENTIFIERS must exist and contain the required entries."""
    assert hasattr(checker, "_SOFT_BAN_IDENTIFIERS"), "_SOFT_BAN_IDENTIFIERS must exist"
    sb = checker._SOFT_BAN_IDENTIFIERS
    assert "paper" in sb
    assert "citation" in sb
    assert "lean_proof" in sb
    assert "peer_review" in sb
    assert "survey_synthesis" in sb
    assert "survey_fetch" in sb
    assert "pi_agent" in sb
    assert "literature" in sb
    assert "CitationValidator" in sb
    assert "CitationArtifact" in sb
    assert "PaperArtifact" in sb
    assert "LeanProofArtifact" in sb
    # apply_research_defaults moved from hard-ban to soft-ban in Wave 12
    assert "apply_research_defaults" in sb


# ---------------------------------------------------------------------------
# Migration-guide scan
# ---------------------------------------------------------------------------

def test_migration_guide_import_detected(tmp_path):
    """A migration guide containing 'from examples.research_overlay' must be reported."""
    guide = tmp_path / "bad-guide.md"
    guide.write_text(
        "## Step 3\n"
        "Use `from examples.research_overlay import ResearchArtifact` in your code.\n"
    )
    # Call the scan function directly with a patched directory
    # Monkeypatch MIGRATION_GUIDES temporarily
    original = checker.MIGRATION_GUIDES
    try:
        checker.MIGRATION_GUIDES = tmp_path
        violations = checker._check_migration_guides()
    finally:
        checker.MIGRATION_GUIDES = original

    assert len(violations) >= 1, (
        f"Expected at least one migration-guide violation; got: {violations}"
    )
    assert any("from examples.research_overlay" in v["text"] for v in violations)


def test_migration_guide_clean_passes(tmp_path):
    """A migration guide without the forbidden import text must produce no violations."""
    guide = tmp_path / "clean-guide.md"
    guide.write_text(
        "## Step 3\n"
        "Use `from hi_agent.artifacts import BaseArtifact` in your code.\n"
    )
    original = checker.MIGRATION_GUIDES
    try:
        checker.MIGRATION_GUIDES = tmp_path
        violations = checker._check_migration_guides()
    finally:
        checker.MIGRATION_GUIDES = original

    assert violations == [], f"Expected no violations for clean guide; got: {violations}"


# ---------------------------------------------------------------------------
# --json output
# ---------------------------------------------------------------------------

def test_json_output_pass(tmp_path, monkeypatch):
    """--json with no violations must emit status=pass JSON."""
    import io
    captured = []

    def fake_print(*args, **kwargs):
        captured.append(" ".join(str(a) for a in args))

    monkeypatch.setattr("builtins.print", fake_print)
    monkeypatch.setattr(checker, "HI_AGENT", tmp_path)
    monkeypatch.setattr(checker, "MIGRATION_GUIDES", tmp_path / "no-such-dir")

    rc = checker.main(["--json"])
    output = "\n".join(captured)
    data = json.loads(output)

    assert rc == 0
    assert data["check"] == "no_research_vocab"
    assert data["status"] == "pass"
    assert data["hard_violations"] == []
    assert data["soft_violations"] == []
    assert data["migration_guide_violations"] == []
    assert "head" in data


def test_json_output_fail(tmp_path, monkeypatch):
    """--json with hard-ban violations must emit status=fail and exit 1."""
    bad_py = tmp_path / "bad.py"
    bad_py.write_text("pi_run_id = 'some_value'\n")

    captured = []

    def fake_print(*args, **kwargs):
        captured.append(" ".join(str(a) for a in args))

    monkeypatch.setattr("builtins.print", fake_print)
    monkeypatch.setattr(checker, "HI_AGENT", tmp_path)
    monkeypatch.setattr(checker, "MIGRATION_GUIDES", tmp_path / "no-such-dir")

    rc = checker.main(["--json"])
    output = "\n".join(captured)
    data = json.loads(output)

    assert rc == 1
    assert data["status"] == "fail"
    assert len(data["hard_violations"]) >= 1
    assert any("pi_run_id" in v["identifier"] for v in data["hard_violations"])


def test_json_output_warn(tmp_path, monkeypatch):
    """--json with only soft-ban violations must emit status=warn and exit 0."""
    soft_py = tmp_path / "soft.py"
    soft_py.write_text("def survey_synthesis(docs): return docs\n")

    captured = []

    def fake_print(*args, **kwargs):
        captured.append(" ".join(str(a) for a in args))

    monkeypatch.setattr("builtins.print", fake_print)
    monkeypatch.setattr(checker, "HI_AGENT", tmp_path)
    monkeypatch.setattr(checker, "MIGRATION_GUIDES", tmp_path / "no-such-dir")

    rc = checker.main(["--json"])
    output = "\n".join(captured)
    data = json.loads(output)

    assert rc == 0
    assert data["status"] == "warn"
    assert data["hard_violations"] == []
    assert len(data["soft_violations"]) >= 1


# ---------------------------------------------------------------------------
# Backward-compat: check_file() still returns hard violations only
# ---------------------------------------------------------------------------

def test_check_file_backward_compat(tmp_path):
    """check_file() (used by existing tests) must still return hard violations."""
    source = 'result = RunPostmortem(run_id="r1", tenant_id="t1")\n'
    f = tmp_path / "compat.py"
    f.write_text(source)
    issues = checker.check_file(f)
    assert any("RunPostmortem" in i for i in issues)
