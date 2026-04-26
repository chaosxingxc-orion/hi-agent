"""Artifact provenance utilities for operation outputs (G-10)."""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path


def hash_artifact(path: Path) -> str:
    """Compute SHA-256 digest of a file, reading in 64 KB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ArtifactRecord:
    uri: str
    sha256: str
    size: int
    mime: str

    @classmethod
    def from_path(cls, path: Path) -> ArtifactRecord:
        p = Path(path)
        mime, _ = mimetypes.guess_type(str(p))
        return cls(
            uri=str(p),
            sha256=hash_artifact(p),
            size=p.stat().st_size,
            mime=mime or "application/octet-stream",
        )
