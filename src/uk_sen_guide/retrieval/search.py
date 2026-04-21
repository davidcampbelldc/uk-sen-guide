"""Search orchestrator — composes BM25 + dense + rerank behind a single API.

Configs:
  * 'bm25'            — BM25 only (lexical baseline — isolated for "when does
                        BM25 beat semantic?" analysis)
  * 'semantic'        — dense only (baseline A)
  * 'hybrid'          — BM25 + dense fused (baseline B)
  * 'hybrid_rerank'   — hybrid + cross-encoder rerank (baseline C)

All four return a common Result shape with score breakdown per retriever,
which is what the eval harness and the /search API both consume.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from .bm25_index import Bm25Index
from .dense_index import DenseIndex
from .fusion import rrf_fuse, weighted_fuse
from .reranker import CrossEncoderReranker

log = logging.getLogger(__name__)

SearchConfig = Literal["bm25", "semantic", "hybrid", "hybrid_rerank"]


@dataclass
class SearchResult:
    chunk_id: str
    doc_id: str | None
    text: str
    section_ref: str | None
    source_ref: dict[str, str] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResponse:
    query_id: str
    results: list[SearchResult]
    latency_ms: int
    config_used: str
    total_candidates: int


class SearchService:
    def __init__(
        self,
        bm25: Bm25Index,
        dense: DenseIndex,
        reranker: CrossEncoderReranker | None = None,
        bm25_weight: float = 0.35,
        dense_weight: float = 0.65,
        fusion_mode: Literal["weighted", "rrf"] = "weighted",
    ):
        self.bm25 = bm25
        self.dense = dense
        self.reranker = reranker or CrossEncoderReranker()
        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight
        self.fusion_mode = fusion_mode

    def search(
        self,
        query: str,
        top_k: int = 5,
        config: SearchConfig = "hybrid_rerank",
        filters: dict[str, Any] | None = None,
        candidate_pool: int = 100,
        rerank_pool: int = 10,
    ) -> SearchResponse:
        t0 = time.perf_counter()
        query_id = f"q-{int(t0 * 1000) & 0xFFFFFFFF:08x}"

        if config == "bm25":
            bm25_hits = self.bm25.search(query, top_k=candidate_pool)
            ranked = [
                (cid, score, {"bm25": score})
                for cid, score in bm25_hits
            ][:top_k]
            total_candidates = len(bm25_hits)
            payload_by_id = {}
            for cid, _ in bm25_hits:
                m = self.bm25.get_chunk(cid)
                if m:
                    payload_by_id[cid] = {
                        "chunk_id": cid,
                        "doc_id": m.get("doc_id"),
                        "text": m.get("text", ""),
                        "section_ref": m.get("section_ref"),
                        **(m.get("metadata") or {}),
                    }
        elif config == "semantic":
            dense_hits = self.dense.search(query, top_k=candidate_pool, filters=filters)
            ranked = [
                (cid, score, {"semantic": score})
                for cid, score, _ in dense_hits
            ][:top_k]
            total_candidates = len(dense_hits)
            payload_by_id = {cid: p for cid, _, p in dense_hits}
        else:
            # Hybrid: BM25 + dense
            bm25_hits = self.bm25.search(query, top_k=candidate_pool)
            dense_hits = self.dense.search(query, top_k=candidate_pool, filters=filters)
            if self.fusion_mode == "rrf":
                fused = rrf_fuse(bm25_hits, dense_hits, top_k=rerank_pool)
            else:
                fused = weighted_fuse(
                    bm25_hits, dense_hits,
                    bm25_weight=self.bm25_weight, dense_weight=self.dense_weight,
                    top_k=rerank_pool,
                )
            payload_by_id = {cid: p for cid, _, p in dense_hits}
            # Fill missing payloads from bm25 manifest
            for cid, _ in bm25_hits:
                if cid not in payload_by_id:
                    m = self.bm25.get_chunk(cid)
                    if m:
                        payload_by_id[cid] = {
                            "chunk_id": cid,
                            "doc_id": m.get("doc_id"),
                            "text": m.get("text", ""),
                            "section_ref": m.get("section_ref"),
                            **(m.get("metadata") or {}),
                        }
            if config == "hybrid":
                ranked = fused[:top_k]
            else:
                # hybrid + cross-encoder rerank
                candidates_for_rerank = []
                for cid, fused_score, breakdown in fused:
                    payload = payload_by_id.get(cid, {})
                    candidates_for_rerank.append({
                        "chunk_id": cid,
                        "text": payload.get("text", ""),
                        "_breakdown": breakdown,
                        "_fused": fused_score,
                    })
                reranked = self.reranker.rerank(query, candidates_for_rerank, top_k=top_k)
                ranked = []
                for cand, rerank_score in reranked:
                    breakdown = dict(cand.get("_breakdown", {}))
                    breakdown["reranker"] = float(rerank_score)
                    fused_score = cand.get("_fused", 0.0)
                    ranked.append((cand["chunk_id"], fused_score, breakdown))
            total_candidates = len(fused)

        results: list[SearchResult] = []
        for cid, fused_score, breakdown in ranked:
            payload = payload_by_id.get(cid, {})
            breakdown_out = dict(breakdown)
            breakdown_out["fused"] = float(fused_score)
            results.append(SearchResult(
                chunk_id=cid,
                doc_id=payload.get("doc_id"),
                text=payload.get("text", ""),
                section_ref=payload.get("section_ref"),
                source_ref={
                    "source": payload.get("source", ""),
                    "section": payload.get("section_ref", "") or "",
                    "url": payload.get("url", ""),
                },
                scores=breakdown_out,
                metadata={
                    k: v for k, v in payload.items()
                    if k not in ("text", "chunk_id", "doc_id")
                },
            ))

        latency_ms = int((time.perf_counter() - t0) * 1000)
        return SearchResponse(
            query_id=query_id,
            results=results,
            latency_ms=latency_ms,
            config_used=config,
            total_candidates=total_candidates,
        )
