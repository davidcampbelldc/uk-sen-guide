# UK SEN Guide

A production-grade hybrid retrieval platform over UK Special Educational
Needs guidance — the retrieval backbone for a future SEN guidance tool.

**The retrieval layer is what this assignment asks for and what is
evaluated here.** A confidence-gated RAG synthesis layer and a minimal
web chat UI ship alongside as a personal demonstrator — documented
but not part of the graded eval. Real user-facing concerns (auth,
privacy beyond disclaimers, accessibility, moderation) remain out of
scope — documented in `docs/ROADMAP.md` as *"what I'd ship next week."*

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
fusion weights. Four configurations are evaluated head-to-head —
`bm25`, `semantic`, `hybrid`, `hybrid_rerank` — on 43 graded queries
across seven query types with Precision@5, Recall@5 and NDCG@5.

## Why this corpus

UK SEN (Special Educational Needs) guidance is a genuinely underserved
space: statutory material is centralised (SEND Code of Practice, DfE)
but the Local Authority tier is fragmented across 152 councils in 152
different formats. Parents navigating the system need both statutory
citations and LA-specific answers. Building the retrieval layer
properly here matters, and the assessment was a clean forcing function
to measure it honestly — so the corpus is real rather than synthetic.

## Documentation

Reviewers — the LEC brief asks for five deliverables. Here's where each
one lives and what it covers:

| # | Deliverable (LEC brief) | File | What's in it |
|---|---|---|---|
| 1 | GitHub repository — main runnable, README, tests passing | this README + `src/`, `tests/`, `pyproject.toml`, `docker-compose.yml` | Setup in 5 commands; 31 tests pass; `ruff` clean; runs on a laptop |
| 2 | Written report (≤2pp) | [`docs/REPORT.md`](docs/REPORT.md) | What I built · real measurements from `eval_runs/` · what broke · what I learnt · honest failure modes |
| 3 | Architecture decisions | [`docs/architecture.md`](docs/architecture.md) | System overview with diagrams · technology choices + why · rejected alternatives + why not · data/retrieval/synthesis pipelines · performance budget · trade-offs summary |
| 4 | "What I'd ship next week" | [`docs/ROADMAP.md`](docs/ROADMAP.md) | Five concrete features sized in days, ordered by impact-per-engineering-day, with reasoning · explicit out-of-scope list |
| 5 | AI-usage note | [`docs/AI_USAGE.md`](docs/AI_USAGE.md) | What I owned · what Claude wrote · AI uses that directly affect the artefact · how I verified · what surprised me |

Additional context a reviewer may want:

| File | Purpose |
|---|---|
| [`STATUS.md`](STATUS.md) | Shipped / in-flight / next — sprint-style dashboard |
| [`docs/ATTRIBUTIONS.md`](docs/ATTRIBUTIONS.md) | Source licences (OGL-3.0 for gov/LA content, charity terms for IPSEA/Contact, MIT for models + libraries) |
| [`eval_runs/README.md`](eval_runs/README.md) | Raw per-query eval outputs + a 15-line reproducer snippet. Every aggregate in REPORT recomputes from these files to 3 decimal places |
| [`eval/queries.yaml`](eval/queries.yaml) | The 43 graded queries with matcher-based ground truth |

## Quick start

Requires Python 3.11+, Docker (for Qdrant).

```bash
# 1. Fetch dependencies
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Start Qdrant
docker compose up -d

# 3. Ingest the corpus (PDFs download on first run; cached after)
python -m uk_sen_guide.ingest

# 4. Build BM25 + dense indices
python -m uk_sen_guide.build_index

# 5. Run the evaluation
python -m uk_sen_guide.eval.run

# 6. Serve the API
uvicorn uk_sen_guide.api.server:app --port 8000
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

43 graded queries across seven types: `statutory-citation`, `symptom-
driven`, `process`, `timing`, `rights-refusal`, `real-parent-scenario`,
`out-of-scope`. Ground truth uses open-schema matchers against chunk
metadata (source, section_ref, local_authority, charity, text-anchor),
so the eval set survives chunker-config changes without manual
re-authoring. Raw per-query run outputs are committed under
`eval_runs/` — reviewers can recompute every aggregate in the REPORT
from those files directly.

Metric implementations are in `src/uk_sen_guide/eval/metrics.py` —
direct P@5, R@5, NDCG@5 rather than wrapping `ranx`, so there is
exactly one source of truth for what's being measured.

## Observability

- `GET /metrics` — Prometheus-compatible counters + latency histograms
  per config, reranker invocation count, candidate-pool sizes.
- Structured JSON logs on stderr — every `/search` call emits one line
  with `query_id`, `config`, `latency_ms`, candidates, returned.

## Load testing

```bash
python -m uk_sen_guide.loadtest --concurrency 20 --duration 30
```

Reports throughput, p50/p95/p99 latency, error rate.

## Repository layout

```
uk-sen-guide/
├── src/uk_sen_guide/
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
│   ├── generation/            # RAG synthesis layer (demonstrator — not evaluated)
│   ├── eval/                  # Graded queries + P/R/NDCG + CLI
│   ├── api/server.py          # FastAPI /search + /health + /metrics + /chat (minimal web UI)
│   ├── observability.py       # structlog + Prometheus
│   ├── ingest.py              # Ingest CLI
│   ├── build_index.py         # Index-build CLI
│   └── loadtest.py            # Concurrency load test CLI
├── tests/                     # hashing · chunking · fusion · metrics
├── eval/queries.yaml          # 43 graded queries with matcher-based qrels
├── eval_runs/                 # Raw per-query eval outputs (committed for reproducibility)
├── docs/
│   ├── REPORT.md              # Written report (deliverable #2)
│   ├── architecture.md        # Architecture decisions + rejected alternatives (#3)
│   ├── ROADMAP.md             # What I'd ship next week (#4)
│   ├── AI_USAGE.md            # Claude Code disclosure (#5)
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
