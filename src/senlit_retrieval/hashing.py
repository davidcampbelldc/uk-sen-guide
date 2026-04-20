"""Content hashing for stable IDs and incremental re-ingest.

Short hex digests are used throughout — full SHA-256 is overkill for the
corpus sizes we handle, and shorter ids keep Qdrant payload sizes sensible.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_text(text: str, salt: str = "") -> str:
    """Short stable hash of a text blob (salt-able for disambiguation)."""
    h = _sha256_hex(f"{salt}\x00{text}".encode())
    return h[:16]  # 64 bits, collision-resistant at our scale


def hash_config(config: dict[str, Any]) -> str:
    """Stable hash of a chunker/embedder config — determines re-processing boundaries."""
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return _sha256_hex(canonical.encode("utf-8"))[:12]


def doc_id(source: str, source_id: str) -> str:
    """Stable doc_id from source provenance."""
    return f"{source}::{hash_text(source_id)}"


def chunk_id(parent_doc_id: str, seq: int, section_ref: str | None = None) -> str:
    """Composite chunk id — human-readable + stable."""
    base = f"{parent_doc_id}::{seq:04d}"
    if section_ref:
        # Section refs may contain '/' or spaces; normalise for safe ids.
        safe = section_ref.replace("/", "_").replace(" ", "_")
        return f"{base}::{safe}"
    return base
