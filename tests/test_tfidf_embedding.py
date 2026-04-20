"""Tests for hi_agent.knowledge.embedding — TFIDFEmbeddingProvider."""

from __future__ import annotations

import math

from hi_agent.knowledge.embedding import (
    TFIDFEmbeddingProvider,
    make_tfidf_embedding_fn,
)
from hi_agent.knowledge.retrieval_engine import cosine_similarity
from hi_agent.knowledge.tfidf import TFIDFIndex

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_index(*docs: str) -> TFIDFIndex:
    """Build a TFIDFIndex populated with the given documents."""
    idx = TFIDFIndex()
    for i, text in enumerate(docs):
        idx.add(f"doc{i}", text)
    # Force IDF rebuild so the vocabulary is ready.
    idx._rebuild_idf()
    return idx


# ---------------------------------------------------------------------------
# 1. embed() returns a vector with correct dimension
# ---------------------------------------------------------------------------

def test_embed_dimension_matches_vocabulary() -> None:
    """embed() must return a vector whose length equals the vocab size."""
    idx = _build_index(
        "machine learning neural network",
        "deep learning gradient descent",
        "natural language processing transformers",
    )
    provider = TFIDFEmbeddingProvider(idx)
    vocab_size = len(idx._idf)

    vec = provider.embed("machine learning")
    assert isinstance(vec, list)
    assert len(vec) == vocab_size, (
        f"Expected vector length {vocab_size}, got {len(vec)}"
    )


# ---------------------------------------------------------------------------
# 2. Returned vector is L2-normalized (unit length)
# ---------------------------------------------------------------------------

def test_embed_vector_is_unit_length() -> None:
    """embed() must return a unit-length (L2-normalized) vector."""
    idx = _build_index(
        "machine learning neural network",
        "deep learning gradient descent",
    )
    provider = TFIDFEmbeddingProvider(idx)

    vec = provider.embed("neural network deep learning")
    norm = math.sqrt(sum(v * v for v in vec))
    # Allow small floating-point tolerance.
    assert abs(norm - 1.0) < 1e-9 or norm == 0.0, (
        f"Expected unit norm, got {norm}"
    )


# ---------------------------------------------------------------------------
# 3. Similar texts score higher than dissimilar texts
# ---------------------------------------------------------------------------

def test_similar_texts_score_higher_than_dissimilar() -> None:
    """Cosine similarity must be higher for similar text pairs."""
    idx = _build_index(
        "machine learning neural network training",
        "deep learning gradient descent optimization",
        "recipe cooking ingredients kitchen",
    )
    provider = TFIDFEmbeddingProvider(idx)

    query_vec = provider.embed("machine learning neural network")
    similar_vec = provider.embed("deep learning neural training gradient")
    dissimilar_vec = provider.embed("recipe cooking kitchen ingredients")

    sim_similar = cosine_similarity(query_vec, similar_vec)
    sim_dissimilar = cosine_similarity(query_vec, dissimilar_vec)

    assert sim_similar > sim_dissimilar, (
        f"Expected sim_similar ({sim_similar:.4f}) > sim_dissimilar ({sim_dissimilar:.4f})"
    )


# ---------------------------------------------------------------------------
# 4. make_tfidf_embedding_fn returns a callable
# ---------------------------------------------------------------------------

def test_make_tfidf_embedding_fn_returns_callable() -> None:
    """make_tfidf_embedding_fn must return a callable."""
    idx = _build_index("hello world", "foo bar baz")
    fn = make_tfidf_embedding_fn(idx)
    assert callable(fn), "make_tfidf_embedding_fn must return a callable"
    # Calling it must return a list of floats.
    result = fn("hello world")
    assert isinstance(result, list)
    assert all(isinstance(v, float) for v in result)


# ---------------------------------------------------------------------------
# 5. embed() on empty/unknown text returns zero vector of correct dimension
# ---------------------------------------------------------------------------

def test_embed_unknown_text_returns_zero_vector() -> None:
    """embed() on text with no vocabulary overlap must return a zero vector."""
    idx = _build_index(
        "machine learning neural network",
        "deep learning gradient",
    )
    provider = TFIDFEmbeddingProvider(idx)
    vocab_size = len(idx._idf)

    # Text with no tokens that appear in the vocabulary.
    vec = provider.embed("zzzzz qqqqqq wwwwwww")
    assert len(vec) == vocab_size
    assert all(v == 0.0 for v in vec), "Unknown tokens must produce a zero vector"
