# Senlit Retrieval

A production-grade hybrid retrieval system over UK Special Educational Needs guidance.

**Status:** work in progress. This is an in-flight build of a submission for an AI engineering assessment. The README will be fleshed out as the system comes together.

## What this is

A `POST /search` API over 1,000+ UK SEN documents — government statutory guidance, the SEND Code of Practice, charity resources (IPSEA, Council for Disabled Children, Contact). Composes three retrievers with tunable weights:

- **BM25** (`bm25s`)
- **Dense semantic** (`BAAI/bge-large-en-v1.5` via `sentence-transformers`, stored in Qdrant)
- **Cross-encoder rerank** (`BAAI/bge-reranker-base`)

Metadata filtering on source, date, and tags (extensible schema for local authority, age band, condition).

An evaluation framework reports precision@5 / recall@5 / NDCG across three configurations — semantic-only, hybrid, hybrid+rerank — against 30-40 graded query/answer pairs covering statutory citation, symptom-driven, process, timing, rights, and out-of-scope queries.

Latency target: p95 < 500ms with rerank; < 200ms without.

## Why this corpus

I'm helping a friend build Senlit — a knowledge tool for parents of SEN children navigating UK government regulations. I run an agent system in production outside this assessment and could have picked Assignment 2 for a safer shipped version. I chose Assignment 1 instead because the retrieval layer for Senlit needs to be right, and this assessment gave me a forcing function to build it properly. Real stakes produce better work than safe choices.

## Setup

_Will expand as the build lands. In rough order:_

```bash
# Requires: Python 3.11+, Docker

docker compose up -d                    # Qdrant on :6333
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python -m senlit_retrieval.ingest       # Ingest corpus (incremental)
uvicorn senlit_retrieval.api:app        # Serve /search
python -m senlit_retrieval.eval         # Run evaluation across 3 configs
```

## Layout

```
src/senlit_retrieval/    # Python package
tests/                   # Pytest suite
data/                    # Corpus (gitignored)
eval_runs/               # Evaluation outputs (gitignored)
docker-compose.yml       # Qdrant service
```

## Development approach

Built in pair-programming mode with Claude Code (Anthropic's CLI agent for software engineering). Full AI-usage disclosure will be added in `docs/AI_USAGE.md` on submission, per professional-practice norms for AI-era take-home assessments.

## Licence

MIT — see `LICENSE`.
