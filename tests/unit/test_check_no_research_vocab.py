"""Test check_no_research_vocab.py catches violations and allows clean code."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_no_research_vocab as chk


def test_pi_run_id_attr_caught(tmp_path):
    code = textwrap.dedent("""
        x = obj.pi_run_id
    """)
    f = tmp_path / "bad.py"
    f.write_text(code)
    issues = chk.check_file(f)
    assert any("pi_run_id" in i for i in issues)


def test_run_postmortem_construction_caught(tmp_path):
    code = textwrap.dedent("""
        result = RunPostmortem(run_id="r1", tenant_id="t1")
    """)
    f = tmp_path / "bad.py"
    f.write_text(code)
    issues = chk.check_file(f)
    assert any("RunPostmortem" in i for i in issues)


def test_legacy_annotation_skips(tmp_path):
    code = textwrap.dedent("""
        x = obj.pi_run_id  # legacy: migration read path
    """)
    f = tmp_path / "ok.py"
    f.write_text(code)
    issues = chk.check_file(f)
    assert not issues


def test_clean_file_passes(tmp_path):
    code = textwrap.dedent("""
        x = obj.lead_run_id
        result = RunRetrospective(run_id="r1", tenant_id="t1")
    """)
    f = tmp_path / "clean.py"
    f.write_text(code)
    issues = chk.check_file(f)
    assert not issues
