# Senlit Retrieval

A production-grade hybrid retrieval platform over UK Special Educational
Needs guidance — the retrieval backbone for a future SEN guidance tool.

**This repo is the retrieval layer.** Answer generation, UI, and real
user-facing concerns (auth, privacy, disclaimers) are deliberately
out of scope — documented in `docs/ROADMAP.md` as *"what I'd ship
next week."* Here we evaluate retrieval itself with rigour.

## What this is

1,215 documents, 8,691 chunks, four document types (PDF · HTML · XLSX ·
text) drawn from five source families:

| Source | Licence | Docs |
|---|---|---|
| SEND Code of Practice 0–25 (2015) | OGL-3.0 | 1 (978 section-aware chunks) |
| gov.uk SEND topic pages | OGL-3.0 | 142 |
| DfE SEN statistics workbooks | OGL-3.0 | 113 sheets |
| Local Authority Local Offers (15 LAs) | OGL-3.0 | 484 |
| IPSEA + Contact articles | attribution | 475 |

The `/search` API composes **BM25** (`bm25s`), **dense embeddings**
(`BAAI/bge-large-en-v1.5`, stored in Qdrant) and an optional
**cross-encoder rerank** (`BAAI/bge-reranker-base`), with tunable
fusion weights. Three configurations are evaluated head-to-head —
`semantic`, `hybrid`, `hybrid_rerank` — on 35 graded queries with
Precision@5, Recall@5 and NDCG@5.

## Why this corpus

UK SEN (Special Educational Needs) guidance is a genuinely underserved
space: statutory material is centralised (SEND Code of Practice, DfE)
but the Local Authority tier is fragmented across 152 councils in 152
different formats. Parents navigating the system need both statutory
citations and LA-specific answers. Building the retrieval layer
properly here matters, and the assessment was a clean forcing function
to measure it honestly — so the corpus is real rather than synthetic.

## Quick start

Requires Python 3.11+, Docker (for Qdrant).

```bash
# 1. Fetch dependencies
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Start Qdrant
docker compose up -d

# 3. Ingest the corpus (PDFs download on first run; cached after)
python -m senlit_retrieval.ingest

# 4. Build BM25 + dense indices
python -m senlit_retrieval.build_index

# 5. Run the evaluation
python -m senlit_retrieval.eval.run

# 6. Serve the API
uvicorn senlit_retrieval.api.server:app --port 8000
```

Health check + first query:

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/search \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "how do I appeal an EHCP decision",
    "top_k": 5,
    "config": "hybrid_rerank",
    "filters": {"source": ["gov.uk/send-cop", "charity-site"]}
  }'
```

Response includes a **per-retriever score breakdown** (`bm25`,
`semantic`, `reranker`, `fused`) for every result.

## Evaluation

35 graded queries across six types: `statutory-citation`, `symptom-
driven`, `process`, `timing`, `rights-refusal`, `out-of-scope`. Ground
truth uses open-schema matchers against chunk metadata (source,
section_ref, local_authority, charity, text-anchor), so the eval set
survives chunker-config changes without manual re-authoring.

Metric implementations are in `src/senlit_retrieval/eval/metrics.py` —
direct P@5, R@5, NDCG@5 rather than wrapping `ranx`, so there is
exactly one source of truth for what's being measured.

## Observability

- `GET /metrics` — Prometheus-compatible counters + latency histograms
  per config, reranker invocation count, candidate-pool sizes.
- Structured JSON logs on stderr — every `/search` call emits one line
  with `query_id`, `config`, `latency_ms`, candidates, returned.

## Load testing

```bash
python -m senlit_retrieval.loadtest --concurrency 20 --duration 30
```

Reports throughput, p50/p95/p99 latency, error rate.

## Repository layout

```
senlit-retrieval/
├── src/senlit_retrieval/
│   ├── models.py              # Document / Chunk / Section / SourceMetadata
│   ├── chunking.py            # FixedSize + HeadingBoundary chunkers
│   ├── hashing.py             # Stable IDs (doc_id, chunk_id, config_hash)
│   ├── sources/               # One adapter per source
│   │   ├── send_cop.py
│   │   ├── gov_uk_send.py
│   │   ├── dfe_tabular.py
│   │   ├── la_local_offer.py
│   │   └── charity_sites.py
│   ├── retrieval/             # BM25 + dense + rerank + fusion + orchestrator
│   ├── eval/                  # Graded queries + P/R/NDCG + CLI
│   ├── api/server.py          # FastAPI /search + /health + /metrics
│   ├── observability.py       # structlog + Prometheus
│   ├── ingest.py              # Ingest CLI
│   ├── build_index.py         # Index-build CLI
│   └── loadtest.py            # Concurrency load test CLI
├── tests/                     # hashing · chunking · fusion · metrics
├── eval/queries.yaml          # Graded queries
├── docs/
│   ├── architecture.md        # Architecture decisions + rejected alternatives
│   ├── ROADMAP.md             # What I'd ship next week
│   ├── REPORT.md              # ≤2pp written report
│   ├── AI_USAGE.md            # Claude Code disclosure
│   └── ATTRIBUTIONS.md        # Source licences (OGL-3.0 etc.)
├── docker-compose.yml         # Qdrant service
├── pyproject.toml
└── STATUS.md                  # Sprint dashboard
```

## Tests

```bash
pytest -q
```

31 tests covering hashing, chunking, fusion, metrics.

## Development approach

Built in pair-programming mode with Claude Code (Anthropic's CLI agent
for software engineering, Opus 4.7). Claude drafted the bulk of the
code; I directed the work, reviewed every commit, and made the
architectural and evaluation-methodology decisions. Full disclosure in
`docs/AI_USAGE.md`.

## Licence

MIT — see `LICENSE`. Source content from gov.uk / DfE / Local
Authorities is Crown copyright under OGL-3.0; charity content is
reproduced under each charity's stated terms. See
`docs/ATTRIBUTIONS.md` for full attribution.
