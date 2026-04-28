"""TDD tests for scripts/_governance/governance_gap.

Two distinct gap definitions:
  - DOCS_ONLY: only docs/** changed (excluding score_caps.yaml and allowlists.yaml
    which are functional governance configs)
  - GOV_INFRA: only docs/**, scripts/**, .github/** changed
    (scripts/.github changes are infrastructure, not product code)

Manifest-freshness uses DOCS_ONLY (strict). Evidence-freshness uses GOV_INFRA (looser).
The W17 cycle was caused by these two definitions being divergently inlined in
multiple files.
"""
from __future__ import annotations

import pytest

from scripts._governance import governance_gap


class TestClassifyFiles:
    def test_empty_returns_none(self) -> None:
        assert governance_gap.classify_files([]) == "none"

    def test_only_docs_returns_docs(self) -> None:
        assert governance_gap.classify_files(["docs/architecture.md"]) == "docs"
        assert (
            governance_gap.classify_files(
                ["docs/releases/x.json", "docs/governance/closure-taxonomy.md"]
            )
            == "docs"
        )

    def test_functional_governance_yaml_is_code(self) -> None:
        assert (
            governance_gap.classify_files(["docs/governance/score_caps.yaml"]) == "code"
        )
        assert (
            governance_gap.classify_files(["docs/governance/allowlists.yaml"]) == "code"
        )

    def test_only_scripts_returns_scripts(self) -> None:
        assert (
            governance_gap.classify_files(["scripts/check_layering.py"]) == "scripts"
        )

    def test_only_workflows_returns_gov(self) -> None:
        assert (
            governance_gap.classify_files([".github/workflows/release-gate.yml"]) == "gov"
        )

    def test_docs_plus_scripts_returns_gov(self) -> None:
        assert (
            governance_gap.classify_files(
                ["docs/x.md", "scripts/check_y.py"]
            )
            == "gov"
        )

    def test_docs_plus_workflow_returns_gov(self) -> None:
        assert (
            governance_gap.classify_files(
                ["docs/x.md", ".github/workflows/release-gate.yml"]
            )
            == "gov"
        )

    def test_scripts_plus_workflow_returns_gov(self) -> None:
        assert (
            governance_gap.classify_files(
                ["scripts/check_y.py", ".github/workflows/x.yml"]
            )
            == "gov"
        )

    def test_any_hi_agent_returns_code(self) -> None:
        assert (
            governance_gap.classify_files(
                ["docs/x.md", "hi_agent/runner.py"]
            )
            == "code"
        )

    def test_any_test_returns_code(self) -> None:
        assert governance_gap.classify_files(["tests/unit/test_x.py"]) == "code"

    def test_pyproject_returns_code(self) -> None:
        assert governance_gap.classify_files(["pyproject.toml"]) == "code"


class TestIsDocsOnlyGap:
    def test_docs_only_passes(self) -> None:
        assert governance_gap.is_docs_only_files(["docs/x.md"]) is True

    def test_scripts_change_fails(self) -> None:
        assert (
            governance_gap.is_docs_only_files(["docs/x.md", "scripts/check_y.py"])
            is False
        )

    def test_workflow_change_fails(self) -> None:
        assert (
            governance_gap.is_docs_only_files([".github/workflows/x.yml"]) is False
        )

    def test_functional_yaml_fails(self) -> None:
        assert (
            governance_gap.is_docs_only_files(["docs/governance/score_caps.yaml"])
            is False
        )

    def test_empty_fails(self) -> None:
        assert governance_gap.is_docs_only_files([]) is False


class TestIsGovOnlyGap:
    def test_docs_only_passes(self) -> None:
        assert governance_gap.is_gov_only_files(["docs/x.md"]) is True

    def test_scripts_only_passes(self) -> None:
        assert (
            governance_gap.is_gov_only_files(["scripts/check_y.py"]) is True
        )

    def test_workflow_only_passes(self) -> None:
        assert (
            governance_gap.is_gov_only_files([".github/workflows/x.yml"]) is True
        )

    def test_docs_plus_scripts_passes(self) -> None:
        assert (
            governance_gap.is_gov_only_files(
                ["docs/x.md", "scripts/check_y.py"]
            )
            is True
        )

    def test_hi_agent_change_fails(self) -> None:
        assert (
            governance_gap.is_gov_only_files(
                ["docs/x.md", "hi_agent/runner.py"]
            )
            is False
        )

    def test_test_change_fails(self) -> None:
        assert (
            governance_gap.is_gov_only_files(["tests/unit/test_x.py"]) is False
        )

    def test_empty_fails(self) -> None:
        assert governance_gap.is_gov_only_files([]) is False


class TestConstants:
    def test_docs_only_excludes_scripts(self) -> None:
        assert "scripts/" not in governance_gap.GAP_DOCS_ONLY

    def test_gov_infra_includes_scripts(self) -> None:
        assert "scripts/" in governance_gap.GAP_GOV_INFRA
        assert "docs/" in governance_gap.GAP_GOV_INFRA
        assert ".github/" in governance_gap.GAP_GOV_INFRA

    def test_functional_yaml_listed(self) -> None:
        assert "docs/governance/score_caps.yaml" in governance_gap.FUNCTIONAL_DOCS_FILES
        assert "docs/governance/allowlists.yaml" in governance_gap.FUNCTIONAL_DOCS_FILES
