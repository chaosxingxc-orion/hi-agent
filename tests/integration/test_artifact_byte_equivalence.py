"""Integration test: artifact content_hash is byte-stable across identical runs.

Verifies that:
1. Two artifact instances built from the same content produce the same content_hash.
2. The seeded MockLLMProvider returns identical text for identical (seed, messages),
   and artifacts built from that text have equal content_hash values.
3. Different seeds produce different content_hash values.

Profile: default-offline (no network, no real LLM, no secrets).
"""

from __future__ import annotations

import pytest
from hi_agent.artifacts.contracts import (
    Artifact,
    DatasetArtifact,
    DocumentArtifact,
    EvidenceArtifact,
    ResourceArtifact,
)
from hi_agent.llm.mock_provider import MockLLMProvider
from hi_agent.llm.protocol import LLMRequest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(content: str) -> LLMRequest:
    return LLMRequest(messages=[{"role": "user", "content": content}])


def _artifact_from_response(text: str) -> Artifact:
    """Build a plain Artifact whose content is the LLM response text."""
    return Artifact(content={"response": text})


# ---------------------------------------------------------------------------
# Content-hash determinism for each artifact type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "artifact_cls,extra_kwargs",
    [
        (Artifact, {}),
        (ResourceArtifact, {}),
        (DocumentArtifact, {}),
        (EvidenceArtifact, {}),
        (DatasetArtifact, {}),
    ],
)
def test_content_hash_same_content_is_stable(artifact_cls, extra_kwargs):
    """Same content dict always yields same content_hash (all artifact types)."""
    content = {"key": "value", "num": 42}
    a1 = artifact_cls(content=content, **extra_kwargs)
    a2 = artifact_cls(content=content, **extra_kwargs)
    assert a1.content_hash, f"{artifact_cls.__name__}: content_hash must not be empty"
    assert a1.content_hash == a2.content_hash, (
        f"{artifact_cls.__name__}: content_hash must be identical for same content"
    )


def test_content_hash_different_content_differs():
    """Different content produces different content_hash."""
    a1 = Artifact(content={"x": 1})
    a2 = Artifact(content={"x": 2})
    assert a1.content_hash != a2.content_hash


def test_content_hash_absent_when_no_content():
    """content_hash stays empty when no content is provided."""
    a = Artifact()
    assert a.content_hash == ""


def test_content_hash_not_overwritten_when_already_set():
    """Explicit content_hash is not overwritten by __post_init__."""
    a = Artifact(content={"x": 1}, content_hash="custom-hash")
    assert a.content_hash == "custom-hash"


# ---------------------------------------------------------------------------
# Seeded MockLLMProvider byte-equivalence through two simulated runs
# ---------------------------------------------------------------------------


def test_seeded_mock_provider_same_seed_same_artifact_hash():
    """Two 'runs' with the same seed and input produce identical artifact content_hash."""
    seed = 7
    user_message = "Summarise the dataset."

    provider = MockLLMProvider(seed=seed)
    req = _make_request(user_message)

    # Simulate run 1
    response_1 = provider.complete(req)
    artifact_1 = _artifact_from_response(response_1.content)

    # Simulate run 2 (same provider instance, same inputs)
    response_2 = provider.complete(req)
    artifact_2 = _artifact_from_response(response_2.content)

    assert response_1.content == response_2.content, (
        "Seeded mock must return identical text for identical inputs"
    )
    assert artifact_1.content_hash == artifact_2.content_hash, (
        "Artifacts from identical seeded responses must have equal content_hash"
    )


def test_seeded_mock_provider_different_seeds_differ():
    """Different seeds produce different responses and different content_hash values."""
    user_message = "Summarise the dataset."
    req = _make_request(user_message)

    a1 = _artifact_from_response(MockLLMProvider(seed=1).complete(req).content)
    a2 = _artifact_from_response(MockLLMProvider(seed=2).complete(req).content)

    assert a1.content_hash != a2.content_hash


def test_seeded_mock_provider_different_inputs_differ():
    """Same seed but different input messages produce different content_hash values."""
    provider = MockLLMProvider(seed=42)
    req_a = _make_request("question A")
    req_b = _make_request("question B")

    a = _artifact_from_response(provider.complete(req_a).content)
    b = _artifact_from_response(provider.complete(req_b).content)

    assert a.content_hash != b.content_hash


def test_no_seed_provider_returns_stable_generic_response():
    """Un-seeded provider always returns the same generic string."""
    provider = MockLLMProvider()
    req = _make_request("anything")
    r1 = provider.complete(req)
    r2 = provider.complete(req)
    assert r1.content == r2.content == "mock response"
