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
- **Retrieval layer**: BM25 · dense (BGE-large, 8,661 points in Qdrant) · cross-encoder rerank · weighted-normalised-sum / RRF fusion · three composable configs
- **API**: FastAPI `POST /search` with per-retriever score breakdown · `GET /health` · `GET /metrics`
- **Observability**: `structlog` JSON logs with `query_id` correlation · Prometheus counters + histograms
- **Eval harness + 43 graded queries**: P@5 / R@5 / NDCG@5 across 7 query types
- **Async load test CLI**: 20 concurrent clients, 0 errors, p95 ≤ 2.3s
- **Hard-mode signals**: cold/warm latency profile · chunker structural comparison · cost per 1,000 queries
- **Deliverable docs**: `README.md` · `docs/REPORT.md` (filled with real numbers) · `docs/architecture.md` · `docs/ROADMAP.md` · `docs/AI_USAGE.md` · `docs/ATTRIBUTIONS.md`
- **Tests**: 31 green (hashing · chunking · fusion · metrics) · ruff clean
- **Phase 1 scrub in progress**: package + code rename to `uk-sen-guide` underway

## In flight 🔄

- **Phase 1** — final verification after rename (tests, ruff, fresh-venv check, GitHub repo rename, local dir rename)
- **Phase 2** — basic RAG answer generation + web chat UI + safeguarding (next)

## Next (4-phase plan)

- **Phase 2** — RAG + web chat UI + safeguarding · 4-5h · beyond Assignment 1
- **Phase 3** — Minimal agent layer (5 SEN-useful tools + planning + parallel + budget) · 2-3h · maps to Assignment 2 pattern
- **Phase 4** — Minimal conversation context optimizer · 1-2h stretch · maps to Assignment 3 pattern
- **Final** — pre-submission check, invite reviewer, send submission email

## Blockers

None.
