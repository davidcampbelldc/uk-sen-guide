# Sprint Status

Living dashboard — updated on every significant commit. Run `git log
--oneline -20` for the fine-grained narrative.

**Target:** ship Wednesday 22 April 2026, 6pm UK.
**Hard cutoff:** Thursday 23 April 2026, end of day UK.

---

## Shipped ✓

- Plan approved and recorded
- Repo scaffolded with clean-room pre-commit + commit-msg hooks
- **Ingest**: 1,215 docs · 8,691 chunks · 6.6 MB text · 4 doc types (PDF / HTML / XLSX / text)
- **Sources covered**: SEND Code of Practice · 142 gov.uk SEND pages · 113 DfE stats workbooks · 484 Local Offer pages across 15 LAs · 399 IPSEA articles · 76 Contact guides
- **BM25 index**: built and persisted
- **Retrieval layer**: BM25 · dense (BGE-large) · cross-encoder rerank · weighted-normalised-sum / RRF fusion · three composable configs (semantic / hybrid / hybrid_rerank)
- **API**: FastAPI `POST /search` with per-retriever score breakdown · `GET /health` · `GET /metrics`
- **Observability**: `structlog` JSON logs with `query_id` correlation · Prometheus counters + histograms
- **Eval harness**: P@5 / R@5 / NDCG@5 · 20 graded queries across 5 types
- **Async load test CLI**: reports throughput + p50/p95/p99 + error rate
- **Deliverable docs**: `docs/architecture.md`, `docs/ROADMAP.md`, `docs/AI_USAGE.md`, `docs/ATTRIBUTIONS.md`
- **Tests**: 31 green (hashing · chunking · fusion · metrics)

## In flight 🔄

- Dense embedding + Qdrant upsert (BGE-large on CPU · 8,691 chunks · ~25 min so far)
- Eval query expansion 20 → 35
- README first-impression polish
- Report shell awaiting eval numbers

## Next

1. Wait for dense index completion
2. Run eval across all 3 configs → first real P@5 / R@5 / NDCG numbers
3. Run cold-cache vs warm-cache latency profile
4. Start API, run concurrency load test at 20 concurrent
5. Fill eval numbers into `docs/REPORT.md`
6. Pre-submission check (every README command in fresh venv)
7. Push, invite reviewer as collaborator, submit

## Blockers

None.

## Deferred (Wednesday scrub commit)

- Rename project: `senlit-retrieval` → `uk-sen-guide` (repo + local dir + Python package + docs + code + User-Agent strings). Single atomic commit.
- Remove working-codename references throughout. Private repo until then.
