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
- **Eval harness + 43 graded queries × 3 configs**: P@5 / R@5 / NDCG@5 across 7 query types · raw run outputs committed under `eval_runs/`
- **Async load test CLI**: 20 concurrent clients, 0 errors, p95 ≤ 2.3s
- **Hard-mode signals**: cold/warm latency profile · chunker structural comparison · cost per 1,000 queries
- **Deliverable docs**: `README.md` · `docs/REPORT.md` (filled with real numbers) · `docs/architecture.md` · `docs/ROADMAP.md` · `docs/AI_USAGE.md` · `docs/ATTRIBUTIONS.md`
- **Tests**: 31 green (hashing · chunking · fusion · metrics) · ruff clean
- **Package rename** to `uk-sen-guide` complete — working-codename references scrubbed
- **Phase 2 demonstrator** (alongside the graded retrieval layer, not evaluated): RAG synthesis with inline citations · dual-provider (Anthropic / z.ai GLM) · 5-state response model (high / medium / low / llm_error / out_of_scope) · confidence gating · GBP cost tracking · minimal web chat UI · safeguarding disclaimers

## In flight 🔄

- **Pre-submission checklist** — README from-scratch verify, ruff, pytest, clean-room scan, GitHub hygiene
- **Submission** — push, email `talent@londonexportcorp.com`

## Next

- **Push + submit** (Wed 22 Apr target / Thu 23 Apr EOD UK hard cutoff)
- **Harden + evaluate the synthesis layer** — hallucination eval, prompt ablation, cost regression, failure-state coverage (ROADMAP #1, ~3 days)
- **Live-demo readiness** for the 30-min technical follow-up call

## Blockers

None.
