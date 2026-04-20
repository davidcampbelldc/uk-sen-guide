"""Dense retrieval index backed by Qdrant + sentence-transformers.

Embedding model: `BAAI/bge-large-en-v1.5` (1024-dim, strong BEIR scores,
CPU-runnable). Encoded in batches and upserted to a local Qdrant collection.
Metadata filtering is done Qdrant-side — we push an open-schema payload
(source, local_authority, doc_type, ...) onto every point.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    Range,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-large-en-v1.5"
DEFAULT_COLLECTION = "senlit_chunks"
DEFAULT_VECTOR_DIM = 1024


class DenseIndex:
    def __init__(
        self,
        collection: str = DEFAULT_COLLECTION,
        model_name: str = DEFAULT_MODEL,
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        batch_size: int = 32,
    ):
        self.collection = collection
        self.model_name = model_name
        self.batch_size = batch_size
        self._client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=60)
        self._encoder: SentenceTransformer | None = None

    @property
    def encoder(self) -> SentenceTransformer:
        if self._encoder is None:
            log.info("loading embedding model %s", self.model_name)
            self._encoder = SentenceTransformer(self.model_name)
        return self._encoder

    def ensure_collection(self, dim: int = DEFAULT_VECTOR_DIM) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if self.collection not in existing:
            log.info("creating Qdrant collection %s (dim=%d)", self.collection, dim)
            self._client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    def upsert(self, chunks: list[dict[str, Any]]) -> int:
        """Embed and upsert chunks in batches. Returns count upserted."""
        self.ensure_collection()
        n = 0
        for batch in _chunked(chunks, self.batch_size):
            texts = [c["text"] for c in batch]
            vectors = self.encoder.encode(
                texts,
                batch_size=self.batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            points = [
                PointStruct(
                    id=_chunk_id_to_point_id(c["chunk_id"]),
                    vector=vectors[i].tolist(),
                    payload={
                        "chunk_id": c["chunk_id"],
                        "doc_id": c.get("doc_id"),
                        "text": c["text"],
                        "section_ref": c.get("section_ref"),
                        **(c.get("metadata") or {}),
                    },
                )
                for i, c in enumerate(batch)
            ]
            self._client.upsert(collection_name=self.collection, points=points)
            n += len(batch)
        log.info("dense index upsert complete: %d chunks", n)
        return n

    def search(
        self,
        query: str,
        top_k: int = 100,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        vector = self.encoder.encode(
            [query], convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False
        )[0].tolist()
        qdrant_filter = _build_filter(filters) if filters else None

        response = self._client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        out: list[tuple[str, float, dict[str, Any]]] = []
        for h in response.points:
            payload = h.payload or {}
            out.append((payload.get("chunk_id", ""), float(h.score), payload))
        return out

    def count(self) -> int:
        try:
            info = self._client.get_collection(self.collection)
            return int(info.points_count or 0)
        except Exception:
            return 0


def _chunked(seq: list[Any], n: int) -> Iterable[list[Any]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _chunk_id_to_point_id(chunk_id: str) -> int:
    """Qdrant accepts uint64 or UUID as ID; we hash chunk_id to a stable uint64."""
    import hashlib

    h = hashlib.sha256(chunk_id.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big", signed=False)


def _build_filter(filters: dict[str, Any]) -> Filter:
    """Translate open-schema filters dict → Qdrant Filter.

    Supported idioms:
      {"source": "gov.uk/send-cop"}              — exact match
      {"source": ["gov.uk/send", "ipsea"]}       — any-of
      {"date_from": "2020-01-01"}                — >=
      {"date_to": "2023-12-31"}                  — <=
      {"local_authority": "Birmingham"}          — match payload key
    """
    must: list[FieldCondition] = []
    for key, val in filters.items():
        if key == "date_from":
            must.append(FieldCondition(key="date", range=Range(gte=val)))
        elif key == "date_to":
            must.append(FieldCondition(key="date", range=Range(lte=val)))
        elif isinstance(val, (list, tuple)):
            must.append(FieldCondition(key=key, match=MatchAny(any=list(val))))
        else:
            must.append(FieldCondition(key=key, match=MatchValue(value=val)))
    return Filter(must=must)
