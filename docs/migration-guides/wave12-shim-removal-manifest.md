# Wave 12 Shim Removal Manifest

All items below are deprecated shims that will be **hard-removed in Wave 12**.
Consumers must migrate before Wave 12 branches. Each row carries a blocking test
that must remain green after removal.

| Symbol / API | Owner | Replacement | Blocking test | Deadline |
|---|---|---|---|---|
| `apply_research_defaults` | CO | `apply_strict_defaults` | tests/unit/llm/test_apply_strict_defaults.py | Wave 12 |
| `CitationArtifact` (from `hi_agent.artifacts.contracts.__getattr__`) | CO | Custom artifact extending `Artifact` in your own package | tests/unit/test_research_artifact_deprecated_import.py | Wave 12 |
| `PaperArtifact`, `LeanProofArtifact` (same shim) | CO | Same as above | tests/unit/test_research_artifact_deprecated_import.py | Wave 12 |
| `ResearchBundle` (`hi_agent.capability.bundles.__getattr__`) | CO | Domain-neutral bundle extending `CapabilityBundle` | tests/unit/test_bundles_research_deprecated.py | Wave 12 |
| `"citations"` evaluation output key | CO | `"evidence_refs"` | tests/unit/test_evaluation_evidence_refs.py | Wave 12 |
| `"research"` `required_posture` value in `ExtensionManifest` | CO | `"strict"` | tests/unit/test_extension_manifest_posture.py | Wave 12 |
| `Posture.RESEARCH` enum value | CO | `Posture.STRICT` (new) | TBD | Wave 12 |
| Tier-preset string keys: `pi_agent`, `paper_writing`, `peer_review`, `survey_synthesis`, `survey_fetch` | CO | Neutral tier-purpose names | TBD | Wave 12 |
| Lazy-import shim in `hi_agent/artifacts/contracts.py` (line ~185) | CO | Remove shim; consumers define own artifact types | tests/unit/test_research_artifact_deprecated_import.py | Wave 12 |

## Migration checklist for consuming teams

1. Replace all `apply_research_defaults(router)` calls with `apply_strict_defaults(router)`.
2. Replace all `from hi_agent.artifacts.contracts import CitationArtifact / PaperArtifact / LeanProofArtifact` with definitions in your own package.
3. Replace all `from hi_agent.capability.bundles import ResearchBundle` with your domain-specific bundle class.
4. Replace all `output["citations"]` keys with `output["evidence_refs"]` in evaluation output dicts.
5. Replace all `required_posture="research"` in `ExtensionManifest` instances with `required_posture="strict"`.
6. If using `Posture.RESEARCH` directly, switch to `Posture.STRICT` once it is added in Wave 12.

## How to verify your migration is complete

Run:
```bash
python scripts/check_no_research_vocab.py
python scripts/check_doc_canonical_symbols.py
```

Both must exit 0. Any remaining `DeprecationWarning` from `hi_agent.*` at test time is a migration gap.
