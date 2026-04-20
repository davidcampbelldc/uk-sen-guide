"""FastAPI server exposing POST /search over the hybrid retrieval pipeline.

Run with:
    uvicorn uk_sen_guide.api.server:app --host 0.0.0.0 --port 8000

Observability:
    GET /health    — service + index size
    GET /metrics   — Prometheus-style metrics (counters + latency histograms)

Logs are emitted as JSON on stderr. Each request gets a `query_id` that
appears on every log line for that request, so tracing a request through
fusion and rerank is grep-by-id.
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import structlog
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

from ..generation.synthesizer import RagSynthesizer
from ..observability import (
    configure_logging,
    get_logger,
    reranker_invocations_total,
    search_candidates_pool,
    search_latency_seconds,
    search_requests_total,
    search_results_returned,
)
from ..retrieval.bm25_index import Bm25Index
from ..retrieval.dense_index import DenseIndex
from ..retrieval.reranker import CrossEncoderReranker
from ..retrieval.search import SearchService

log = get_logger(__name__)


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


# Process-wide service — set at startup
_service: SearchService | None = None
_synthesizer: RagSynthesizer | None = None

_HERE = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_HERE / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(level=os.environ.get("UK_SEN_LOG_LEVEL", "INFO"))
    global _service, _synthesizer
    index_dir = Path(os.environ.get("UK_SEN_INDEX_DIR", "data/index"))
    log.info("service.startup", phase="loading-indices", index_dir=str(index_dir))
    bm25 = Bm25Index()
    bm25.load(index_dir / "bm25")
    dense = DenseIndex(
        collection=os.environ.get("UK_SEN_QDRANT_COLLECTION", "uk_sen_chunks"),
        qdrant_host=os.environ.get("UK_SEN_QDRANT_HOST", "localhost"),
        qdrant_port=int(os.environ.get("UK_SEN_QDRANT_PORT", "6333")),
    )
    reranker = CrossEncoderReranker()
    _service = SearchService(bm25=bm25, dense=dense, reranker=reranker)
    _synthesizer = RagSynthesizer()
    log.info(
        "service.ready",
        bm25_chunks=bm25.size,
        dense_points=dense.count(),
        synthesizer_enabled=_synthesizer.client is not None,
    )
    yield
    log.info("service.shutdown")


app = FastAPI(
    title="UK SEN Guide",
    description="Hybrid retrieval (BM25 + dense + cross-encoder rerank) over UK SEN guidance.",
    version="0.1.0",
    lifespan=lifespan,
)

# Expose /metrics with default HTTP metrics + our custom ones
Instrumentator().instrument(app).expose(app, include_in_schema=False, endpoint="/metrics")

# Serve static assets for the web UI
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def chat_ui(request: Request) -> HTMLResponse:
    """Render the chat UI — minimal HTML + vanilla JS."""
    return _TEMPLATES.TemplateResponse(request, "index.html")


@app.post("/chat", response_class=HTMLResponse, include_in_schema=False)
def chat_submit(
    request: Request,
    query: str = Form(..., min_length=1, max_length=1000),
    config: Literal["semantic", "hybrid", "hybrid_rerank"] = Form("hybrid"),
) -> HTMLResponse:
    """Handle form POST: retrieve + synthesize + render as HTML fragment."""
    if _service is None or _synthesizer is None:
        raise HTTPException(status_code=503, detail="service not ready")

    t0 = time.perf_counter()
    retrieval = _service.search(query=query, top_k=5, config=config)
    synth = _synthesizer.synthesize(query, retrieval.results)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    structlog.get_logger(__name__).bind(
        query_id=retrieval.query_id,
        config=config,
    ).info(
        "chat.ok",
        retrieval_ms=retrieval.latency_ms,
        total_ms=latency_ms,
        confidence=synth.confidence,
        escalated=synth.escalated,
        input_tokens=synth.input_tokens,
        output_tokens=synth.output_tokens,
    )

    return _TEMPLATES.TemplateResponse(
        request,
        "answer.html",
        {
            "query": query,
            "answer": synth.answer,
            "confidence": synth.confidence,
            "escalated": synth.escalated,
            "citations": synth.citations,
            "disclaimer": synth.disclaimer,
            "latency_ms": latency_ms,
            "cost_gbp": synth.cost_gbp,
            "config_used": retrieval.config_used,
        },
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

    t0 = time.perf_counter()
    config = req.config
    try:
        resp = _service.search(
            query=req.query,
            top_k=req.top_k,
            config=config,
            filters=req.filters,
        )
    except Exception as exc:
        search_requests_total.labels(config=config, status="error").inc()
        log.error(
            "search.error",
            config=config,
            error=str(exc),
            error_type=type(exc).__name__,
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
        raise HTTPException(status_code=500, detail="search failed") from exc

    # Metrics
    elapsed = time.perf_counter() - t0
    search_requests_total.labels(config=config, status="ok").inc()
    search_latency_seconds.labels(config=config).observe(elapsed)
    search_candidates_pool.labels(config=config).observe(resp.total_candidates)
    search_results_returned.labels(config=config).observe(len(resp.results))
    if config == "hybrid_rerank":
        reranker_invocations_total.inc()

    # Bind query_id into log context so logs correlate
    log_ = structlog.get_logger(__name__).bind(
        query_id=resp.query_id,
        config=config,
    )
    log_.info(
        "search.ok",
        latency_ms=resp.latency_ms,
        candidates=resp.total_candidates,
        returned=len(resp.results),
        has_filters=bool(req.filters),
        top_k=req.top_k,
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
