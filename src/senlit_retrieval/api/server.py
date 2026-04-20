"""FastAPI server exposing POST /search over the hybrid retrieval pipeline.

Run with:
    uvicorn senlit_retrieval.api.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..retrieval.bm25_index import Bm25Index
from ..retrieval.dense_index import DenseIndex
from ..retrieval.reranker import CrossEncoderReranker
from ..retrieval.search import SearchConfig, SearchService

log = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(5, ge=1, le=50)
    config: Literal["semantic", "hybrid", "hybrid_rerank"] = "hybrid_rerank"
    filters: dict[str, Any] | None = None


class ResultScore(BaseModel):
    bm25: float | None = None
    semantic: float | None = None
    reranker: float | None = None
    fused: float | None = None


class SearchResultModel(BaseModel):
    chunk_id: str
    doc_id: str | None
    text: str
    section_ref: str | None
    source_ref: dict[str, str]
    scores: ResultScore
    metadata: dict[str, Any]


class SearchResponseModel(BaseModel):
    query_id: str
    results: list[SearchResultModel]
    latency_ms: int
    config_used: str
    total_candidates: int


# Globals — set at startup
_service: SearchService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _service
    index_dir = Path(os.environ.get("SENLIT_INDEX_DIR", "data/index"))
    log.info("loading indices from %s", index_dir)
    bm25 = Bm25Index()
    bm25.load(index_dir / "bm25")
    dense = DenseIndex(
        collection=os.environ.get("SENLIT_QDRANT_COLLECTION", "senlit_chunks"),
        qdrant_host=os.environ.get("SENLIT_QDRANT_HOST", "localhost"),
        qdrant_port=int(os.environ.get("SENLIT_QDRANT_PORT", "6333")),
    )
    reranker = CrossEncoderReranker()
    _service = SearchService(bm25=bm25, dense=dense, reranker=reranker)
    log.info("service ready — BM25 %d chunks, Qdrant %d points", bm25.size, dense.count())
    yield
    log.info("shutdown")


app = FastAPI(
    title="Senlit Retrieval",
    description="Hybrid retrieval (BM25 + dense + cross-encoder rerank) over UK SEN guidance.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, Any]:
    if _service is None:
        raise HTTPException(status_code=503, detail="service not ready")
    return {
        "status": "ok",
        "bm25_chunks": _service.bm25.size,
        "dense_points": _service.dense.count(),
    }


@app.post("/search", response_model=SearchResponseModel)
def search(req: SearchRequest) -> SearchResponseModel:
    if _service is None:
        raise HTTPException(status_code=503, detail="service not ready")
    resp = _service.search(
        query=req.query,
        top_k=req.top_k,
        config=req.config,
        filters=req.filters,
    )
    return SearchResponseModel(
        query_id=resp.query_id,
        results=[
            SearchResultModel(
                chunk_id=r.chunk_id,
                doc_id=r.doc_id,
                text=r.text,
                section_ref=r.section_ref,
                source_ref=r.source_ref,
                scores=ResultScore(
                    bm25=r.scores.get("bm25"),
                    semantic=r.scores.get("semantic"),
                    reranker=r.scores.get("reranker"),
                    fused=r.scores.get("fused"),
                ),
                metadata=r.metadata,
            )
            for r in resp.results
        ],
        latency_ms=resp.latency_ms,
        config_used=resp.config_used,
        total_candidates=resp.total_candidates,
    )
