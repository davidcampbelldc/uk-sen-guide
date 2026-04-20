"""Structured logging + Prometheus metrics for the retrieval service.

Single source of truth for observability wiring. The API server imports from
here to instrument itself; standalone scripts (ingest, build_index, eval)
can also import ``configure_logging`` for consistent JSON log output.

Metrics exposed at `/metrics` by prometheus-fastapi-instrumentator:
  * default HTTP metrics (requests_total, request_duration_seconds, ...)
  * custom counters defined below — per-config search counts, result sizes,
    reranker invocations.

Structured JSON logs include:
  timestamp, level, logger, event, query_id (when applicable), config,
  latency_ms, candidate_count, error (on failure).
"""

from __future__ import annotations

import logging
import sys

import structlog
from prometheus_client import Counter, Histogram

# ── Custom metrics ────────────────────────────────────────────────────────
search_requests_total = Counter(
    "senlit_search_requests_total",
    "Search requests by config and status.",
    ["config", "status"],
)

search_latency_seconds = Histogram(
    "senlit_search_latency_seconds",
    "End-to-end search latency by config.",
    ["config"],
    buckets=(0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 2.0, 5.0),
)

search_candidates_pool = Histogram(
    "senlit_search_candidates_pool",
    "Size of candidate pool before fusion/rerank.",
    ["config"],
    buckets=(1, 10, 25, 50, 100, 200, 500),
)

search_results_returned = Histogram(
    "senlit_search_results_returned",
    "Number of results returned per query.",
    ["config"],
    buckets=(0, 1, 3, 5, 10, 25, 50),
)

reranker_invocations_total = Counter(
    "senlit_reranker_invocations_total",
    "Cross-encoder reranker invocations.",
)


# ── Logging configuration ─────────────────────────────────────────────────
def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog for JSON output on stderr.

    Call once at process startup. Safe to re-call (structlog is idempotent).
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name or "senlit")
