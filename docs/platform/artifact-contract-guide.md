# Artifact Contract Guide

This guide defines the platform's typed artifact system.  Upper-layer agents
produce and consume artifacts through the capability/harness layer.  Artifacts
are the platform's unit of evidence and data flow — they carry no domain
semantics by design.

---

## Artifact Type Hierarchy

All artifact types are defined in `hi_agent/artifacts/contracts.py`.

```
Artifact (base)
├── ResourceArtifact      — a discovered URL or API endpoint
├── DocumentArtifact      — extracted document content
├── StructuredDataArtifact — typed JSON or tabular data
├── EvidenceArtifact      — a claim with a confidence score
└── EvaluationArtifact    — the result of an evaluation pass
```

### Stable Fields (all types)

Every `Artifact` instance carries these fields.  Upper layers may rely on them
being present regardless of subtype.

| Field | Type | Description |
|---|---|---|
| `artifact_id` | `str` | Auto-generated 12-hex-char unique identifier. |
| `artifact_type` | `str` | String tag set by `__post_init__` in each subclass (e.g. `"evidence"`, `"document"`). |
| `producer_action_id` | `str` | ID of the capability action that produced this artifact. |
| `source_refs` | `list[str]` | Upstream artifact IDs that were consumed to produce this one (lineage chain). |
| `metadata` | `dict[str, Any]` | Free-form bag for caller-supplied annotations. |
| `provenance` | `dict[str, Any]` | Populated by `OutputToArtifactAdapter` — records `capability_action_id` and `adapter` name. |
| `upstream_artifact_ids` | `list[str]` | Lineage: artifact IDs that were inputs to producing this artifact. |
| `created_at` | `str` | UTC ISO-8601 timestamp set at construction time. |
| `content` | `Any` | Raw content payload. Set on base `Artifact`; subclasses use typed fields instead. |

### Subtype-Specific Fields

| Type | Extra Fields |
|---|---|
| `ResourceArtifact` | `url`, `title`, `snippet` |
| `DocumentArtifact` | `url`, `title`, `text`, `word_count` |
| `StructuredDataArtifact` | `schema_id`, `data` |
| `EvidenceArtifact` | `claim`, `confidence`, `evidence_type` (`"direct"` / `"indirect"` / `"counter"`) |
| `EvaluationArtifact` | `score`, `passed`, `criteria` (dict), `feedback` |

---

## OutputToArtifactAdapter — Inference Rules

`OutputToArtifactAdapter` (`hi_agent/artifacts/adapters.py`) converts a raw
capability output dict into a typed artifact.  The inference is first-match:

| Condition | Resulting type |
|---|---|
| output has `url` **and** `title` | `ResourceArtifact` |
| output has `claim` **and** `confidence` | `EvidenceArtifact` |
| output has `score` **and** `passed` | `EvaluationArtifact` |
| output has `data` **and** `schema_id` | `StructuredDataArtifact` |
| output has `url` only (no title) | `DocumentArtifact` |
| anything else | `Artifact` (base, raw content preserved) |

Non-dict outputs are wrapped in `{"output": <value>}` before inference.

```python
from hi_agent.artifacts.adapters import OutputToArtifactAdapter

adapter = OutputToArtifactAdapter()
artifacts = adapter.adapt(
    action_id="search_action_001",
    output={"url": "https://example.com/paper", "title": "Study on X"},
    source_refs=[],
)
# artifacts[0] is a ResourceArtifact
```

---

## ArtifactRegistry — Storage and Queries

`ArtifactRegistry` (`hi_agent/artifacts/registry.py`) is an in-memory store.

```python
from hi_agent.artifacts.registry import ArtifactRegistry

registry = ArtifactRegistry()

# Store
registry.store(artifact)

# Retrieve by ID
art = registry.get("abc123def456")

# Query by type
evidence_arts = registry.query(artifact_type="evidence")

# Query by producer
arts = registry.query(producer_action_id="search_action_001")
```

`query()` accepts `artifact_type` and/or `producer_action_id` as keyword
filters.  Both may be combined.  `all()` returns every stored artifact.

---

## Rule: Upper Layers Build Domain Objects FROM Artifacts

Upper-layer agents must not subclass `Artifact` directly with domain-specific
fields.  The platform artifact hierarchy is closed to extension from above.

Instead, define domain objects that are constructed from platform artifacts:

```python
from dataclasses import dataclass
from hi_agent.artifacts.contracts import EvidenceArtifact
from hi_agent.artifacts.registry import ArtifactRegistry


@dataclass
class RNDFinding:
    """Domain object for an R&D research finding."""
    claim: str
    confidence: float
    source_artifact_id: str
    evidence_type: str


def collect_findings(registry: ArtifactRegistry) -> list[RNDFinding]:
    """Map platform EvidenceArtifacts to domain RNDFinding objects."""
    findings = []
    for art in registry.query(artifact_type="evidence"):
        assert isinstance(art, EvidenceArtifact)
        findings.append(
            RNDFinding(
                claim=art.claim,
                confidence=art.confidence,
                source_artifact_id=art.artifact_id,
                evidence_type=art.evidence_type,
            )
        )
    return findings
```

This keeps domain semantics out of the platform layer and makes both sides
independently evolvable.

---

## Key Source Locations

| Component | File |
|---|---|
| `Artifact` hierarchy | `hi_agent/artifacts/contracts.py` |
| `OutputToArtifactAdapter` | `hi_agent/artifacts/adapters.py` |
| `ArtifactRegistry` | `hi_agent/artifacts/registry.py` |
