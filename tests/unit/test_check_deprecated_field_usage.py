"""Test check_deprecated_field_usage catches pi_run_id usage."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_deprecated_field_usage as chk


def test_pi_run_id_access_detected(tmp_path):
    code = textwrap.dedent("""
        tr = some_team_run
        x = tr.pi_run_id
    """)
    f = tmp_path / "bad.py"
    f.write_text(code)
    issues = chk.check_pi_run_id_usage(f)
    assert issues


def test_lead_run_id_clean(tmp_path):
    code = textwrap.dedent("""
        tr = some_team_run
        x = tr.lead_run_id
    """)
    f = tmp_path / "good.py"
    f.write_text(code)
    issues = chk.check_pi_run_id_usage(f)
    assert not issues
