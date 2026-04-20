"""BM25 index backed by bm25s (fast pure-Python).

We persist the index and the chunk manifest (id + metadata) separately so
the index can be reloaded without re-ingesting the corpus. Tokenisation is
the default bm25s Stemmer pipeline (lowercase + punctuation strip + English
stemmer), chosen for simplicity and widely-understood behaviour.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import bm25s
import numpy as np

log = logging.getLogger(__name__)


class Bm25Index:
    """Thin wrapper around bm25s with on-disk persistence + chunk manifest.

    The manifest stores the chunk_id -> {text, metadata} mapping so the
    index can return full chunk records (not just numeric indices).
    """

    def __init__(self) -> None:
        self._retriever: bm25s.BM25 | None = None
        self._chunk_ids: list[str] = []
        self._manifest: dict[str, dict[str, Any]] = {}

    def build(self, chunks: list[dict[str, Any]]) -> None:
        """Build the index from a list of chunk dicts (each with 'chunk_id' + 'text' + 'metadata')."""
        texts = [c["text"] for c in chunks]
        tokenised = bm25s.tokenize(texts, stopwords="en", show_progress=False)
        retriever = bm25s.BM25()
        retriever.index(tokenised, show_progress=False)

        self._retriever = retriever
        self._chunk_ids = [c["chunk_id"] for c in chunks]
        self._manifest = {
            c["chunk_id"]: {
                "text": c["text"],
                "metadata": c.get("metadata", {}),
                "doc_id": c.get("doc_id"),
                "section_ref": c.get("section_ref"),
            }
            for c in chunks
        }
        log.info("BM25 index built: %d chunks", len(chunks))

    def save(self, out_dir: Path) -> None:
        if self._retriever is None:
            raise RuntimeError("cannot save: index not built")
        out_dir.mkdir(parents=True, exist_ok=True)
        self._retriever.save(str(out_dir / "bm25"))
        (out_dir / "chunk_ids.json").write_text(json.dumps(self._chunk_ids))
        (out_dir / "manifest.json").write_text(json.dumps(self._manifest))
        log.info("BM25 index saved to %s", out_dir)

    def load(self, out_dir: Path) -> None:
        self._retriever = bm25s.BM25.load(str(out_dir / "bm25"), load_corpus=False)
        self._chunk_ids = json.loads((out_dir / "chunk_ids.json").read_text())
        self._manifest = json.loads((out_dir / "manifest.json").read_text())
        log.info("BM25 index loaded from %s (%d chunks)", out_dir, len(self._chunk_ids))

    def search(self, query: str, top_k: int = 100) -> list[tuple[str, float]]:
        if self._retriever is None:
            raise RuntimeError("index not built or loaded")
        tokenised = bm25s.tokenize([query], stopwords="en", show_progress=False)
        results, scores = self._retriever.retrieve(tokenised, k=min(top_k, len(self._chunk_ids)), show_progress=False)
        # bm25s returns arrays shape (n_queries, k)
        row_idx = np.asarray(results[0]).tolist()
        row_scores = np.asarray(scores[0]).tolist()
        out: list[tuple[str, float]] = []
        for idx, score in zip(row_idx, row_scores, strict=False):
            if 0 <= idx < len(self._chunk_ids):
                out.append((self._chunk_ids[idx], float(score)))
        return out

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        return self._manifest.get(chunk_id)

    @property
    def size(self) -> int:
        return len(self._chunk_ids)
