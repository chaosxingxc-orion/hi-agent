"""Lightweight TF-IDF-based pseudo-embedding provider.

Bridges TFIDFIndex's internal term space to RetrievalEngine's
embedding_fn interface, activating Layer 4 without external dependencies.

Only uses Python standard library (math, collections).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable

from hi_agent.knowledge.tfidf import TFIDFIndex

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """Whitespace + lowering tokenizer, strips punctuation."""
    cleaned = _PUNCT_RE.sub(" ", text.lower())
    return [tok for tok in cleaned.split() if tok]


class TFIDFEmbeddingProvider:
    """Produces pseudo-embeddings from TF-IDF term vectors.

    Bridges the TFIDFIndex's internal term space to RetrievalEngine's
    embedding_fn interface, activating Layer 4 without external dependencies.

    The embedding dimension equals the vocabulary size of the underlying
    TFIDFIndex at the time embed() is called.  Vectors are L2-normalized
    so that cosine_similarity reduces to a simple dot product.
    """

    def __init__(self, tfidf_index: TFIDFIndex) -> None:
        """Initialize with a TFIDFIndex instance."""
        self._tfidf = tfidf_index

    def embed(self, text: str) -> list[float]:
        """Convert text to a normalized TF-IDF vector.

        Steps:
        1. Ensure the IDF table is up to date (rebuilds if dirty).
        2. Tokenize the input text.
        3. For each term in the IDF vocabulary, compute TF * IDF.
        4. L2-normalize the resulting vector.
        5. Return as list[float].

        Returns a zero vector (all zeros) when the vocabulary is empty or
        the text contains no known terms.
        """
        # Ensure IDF table is current.
        if self._tfidf._dirty:
            self._tfidf._rebuild_idf()

        vocab = self._tfidf._idf
        if not vocab:
            return []

        tokens = _tokenize(text)
        if not tokens:
            return [0.0] * len(vocab)

        tf = Counter(tokens)
        # Build vector aligned with sorted vocabulary for determinism.
        terms = sorted(vocab.keys())
        vec = [tf.get(term, 0) * vocab[term] for term in terms]

        # L2 normalize.
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec  # all-zero vector — cosine similarity will be 0

        return [v / norm for v in vec]

    def as_callable(self) -> Callable[[str], list[float]]:
        """Return self.embed as a Callable for RetrievalEngine."""
        return self.embed


def make_tfidf_embedding_fn(tfidf_index: TFIDFIndex) -> Callable[[str], list[float]]:
    """Factory: create an embedding callable from a TFIDFIndex.

    Usage::

        fn = make_tfidf_embedding_fn(engine._tfidf)
        engine = RetrievalEngine(..., embedding_fn=fn)
    """
    return TFIDFEmbeddingProvider(tfidf_index).as_callable()
