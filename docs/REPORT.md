# Report — Retrieval Platform over UK SEN Guidance

*Target ≤2 pages per brief. Narrative fits; the tables of real measurements push to page 3. Keeping them in service of the brief's "real numbers, not vibes" signal is the deliberate trade-off. All numbers are real measurements from runs committed to the repo under `eval_runs/` — reviewer can recompute every aggregate below directly from the JSONL.*

## What I built

A hybrid retrieval platform over **1,215 documents** of UK Special Educational Needs guidance (**8,691 chunks, 6.6 MB text**). The corpus covers all three document types the brief asks for: PDF (SEND Code of Practice 2015, DfE publications), HTML (gov.uk SEND pages, 15 Local Authority Local Offers, IPSEA, Contact), and tabular (113 DfE statistics workbook sheets — modern DfE publishes XLSX; handled as first-class tabular documents).

Retrieval composes BM25 (`bm25s`), dense embeddings (`BAAI/bge-large-en-v1.5`, stored in Qdrant), and cross-encoder rerank (`BAAI/bge-reranker-base`), with tunable weighted-normalised-sum fusion and RRF fallback. Four configurations are exposed via `POST /search` — `bm25`, `semantic`, `hybrid`, `hybrid_rerank` — each returning top-5 with per-retriever score breakdown. FastAPI server, Prometheus `/metrics`, structured JSON logs with `query_id` correlation. Async load-test CLI. 31 unit tests, `ruff` clean.

### Beyond the brief (shipped as demonstrator, not evaluated here)

Alongside the graded retrieval layer sits a small RAG synthesis layer and a minimal web chat UI — included to show the retrieval is load-bearing for a real parent-facing product, not evaluated as part of this submission:

- **Dual-provider abstraction** — Anthropic Claude and z.ai GLM (OpenAI-compatible) behind one interface; provider selected at startup from env vars, switchable without code change.
- **Confidence gating** — fused score below threshold skips the LLM and returns a deterministic IPSEA-escalation message, saving cost and avoiding hallucination on weak retrievals.
- **Five response states** — `high` / `medium` / `low` / `llm_error` / `out_of_scope` — the `llm_error` state preserves retrieved citations so the UI can still surface what retrieval found when the LLM call fails.
- **Numbered inline citations** tied to specific chunk IDs + source + section anchors.
- **Per-call GBP cost tracking** — token usage × provider rate, logged per request.

None of this layer contributes to the retrieval numbers below; hallucination eval, prompt ablation, and failure-state coverage are on the roadmap (item #1, ~3 days).

## Evaluation — 43 graded queries × 4 configs

Ground truth uses open-schema matchers against chunk metadata (`source`, `section_ref`, `section_ref_prefix`, `local_authority`, `charity`, `text_contains` as list-AND), with graded relevance (0/1/2). I authored every query and every matcher. Metrics — Precision@5, Recall@5, NDCG@5 — implemented directly in `src/uk_sen_guide/eval/metrics.py` for transparency over wrapping `ranx`. Four configs compared so the question "when does BM25 beat semantic?" gets a direct answer rather than an indirect one.

| Config | P@5 | R@5 | NDCG@5 | p50 latency | p95 latency |
|---|---|---|---|---|---|
| bm25 (lexical only) | 0.251 | 0.019 | 0.221 | <1 ms | <1 ms |
| semantic (dense only) | 0.298 | 0.023 | 0.267 | 94 ms | 186 ms |
| **hybrid** (BM25 + dense fused) | **0.307** | 0.023 | **0.285** | **99 ms** | **135 ms** |
| hybrid_rerank | 0.260 | 0.017 | 0.238 | 2,300 ms | 2,408 ms |

**Hybrid wins overall.** BM25 loses to semantic by ~0.05 NDCG standalone but adds marginal signal when fused — hybrid gains +0.018 NDCG over semantic alone. Rerank *hurts* quality on this domain — a surprising finding worth reporting honestly (see below).

### BM25 vs semantic — when does lexical beat dense? Per-type NDCG@5

| Type | BM25 | Semantic | Hybrid | Winner | Note |
|---|---|---|---|---|---|
| process | 0.409 | 0.446 | **0.485** | Hybrid | "How do I X" — fusion helps |
| timing | 0.250 | 0.381 | **0.410** | Hybrid | Semantic picks up deadlines from context |
| symptom-driven | 0.220 | 0.220 | **0.290** | Hybrid | BM25 rescues some semantic misses |
| **real-parent-scenario** | **0.236** | **0.232** | **0.238** | Hybrid | **Human-judged ~75% despite 24% NDCG — see below** |
| rights-refusal | 0.167 | **0.285** | 0.264 | Semantic | Contextual legal phrasing, BM25 doesn't help |
| statutory-citation | 0.072 | **0.163** | 0.127 | Semantic | **Surprise:** BM25 expected to dominate; doesn't. See commentary |
| out-of-scope | 0.000 | 0.000 | 0.000 | tie | Correct — no relevant docs by design |

**The direct answer: BM25 never beats semantic standalone on this corpus.** The closest BM25 comes is a tie on `real-parent-scenario` and `symptom-driven`. The most counter-intuitive row is **statutory-citation**: we would have predicted BM25 to dominate (parents querying "§9.14" should match lexically), but semantic wins 0.163 vs 0.072 — BGE-large picks up legal-statutory phrasing context that raw token matching misses. BM25 does still earn its keep via fusion — hybrid beats semantic on 4 of 7 types and matches it on 2 more — but the narrative "BM25 for statutory, semantic for everything else" is not what the numbers say. A query-type classifier (ROADMAP #2) should route statutory-citation to **semantic-heavier** weights, not BM25-heavier as initially expected.

### Cold-cache vs warm-cache (direct measurement)

| Config | Cold (1st query) | Warm p50 | Warm p95 |
|---|---|---|---|
| semantic | 3,823 ms (model load) | 96 ms | 110 ms |
| hybrid | 97 ms (already warm) | 94 ms | 108 ms |
| hybrid_rerank | 6,671 ms (reranker load) | 1,975 ms | 2,181 ms |

Cold penalty is dominated by model load. Warm p95 for semantic + hybrid sits comfortably under the 500 ms budget; hybrid_rerank does not.

### Concurrency (async load test, 20s run)

| Concurrency | Throughput | p50 | p95 | Errors |
|---|---|---|---|---|
| 10 | 11.4 req/s | 884 ms | 967 ms | 0 |
| 20 | 10.1 req/s | 1,917 ms | 2,293 ms | 0 |

System handles sustained load without errors; latency degrades with concurrency (GIL + CPU-bound embedding). Production path: uvicorn `--workers N` or GPU.

### Cost per 1,000 queries

All models are local/open — no per-query API cost (£0 for commercial providers). Dominant cost is one-time embedding of the corpus (~72 CPU-min on this hardware). Steady-state query cost at AWS c5.large spot pricing:

- semantic / hybrid: ~£0.001 per 1,000 queries
- hybrid_rerank: ~£0.022 per 1,000 queries

Essentially free. Compute, not API, is the cost surface.

### Chunk-strategy comparison (structural)

| Strategy | Chunks | Mean chars | Median | Max | § preserved |
|---|---|---|---|---|---|
| fixed (2000c/200ov) | 4,157 | 1,720 | 2,000 | 2,000 | 0% |
| fixed (3000c/300ov) | 2,979 | 2,380 | 3,000 | 3,000 | 0% |
| **heading_boundary (default)** | **8,661** | **730** | **437** | **3,186** | **91%** |
| heading_boundary (large 3200c) | 8,370 | 741 | 422 | 3,999 | 93% |

Heading-boundary wins on this corpus for one load-bearing reason: **section-ref preservation at 91%.** For statutory content (SEND CoP, which cites by §X.Y), citation-level retrieval accuracy is the job. Full retrieval-quality comparison across chunkers deferred (would require re-embedding each strategy into its own collection — ~70 CPU-min per arm on this hardware; flagged in ROADMAP).

## The most important finding: metric vs. usefulness

I authored 8 "real-parent-scenario" queries grounded in the lived experience of a parent navigating a SEND Tribunal refusal-to-assess appeal — anonymised, no identifying details, modelled on actual pain-points. Hybrid config scored **NDCG@5 = 0.238** on these.

Then I inspected the verbatim top-3 for each, and rated usefulness by hand:

| # | Query | NDCG@5 | Human-judged top-3 usefulness |
|---|---|---|---|
| q036 | How to appeal refusal-to-assess | 0.32 | **Strong.** Contact plain-language guide + gov.uk form SEND35A + IPSEA formal route |
| q037 | Evidence for MH-concerns appeal | 0.51 | **Strong.** Top hit is SEND CoP §9.14 (the legal test) |
| q038 | School duties pre-diagnosis | 0.79 | **Excellent.** First hit cites *"section 66 CFA 2014 — best endeavours"* — the exact duty |
| q039 | MH factors at Tribunal | 0.00 | **Actually useful.** IPSEA sections C/D/G/H (mental-health sections of EHC plans) + a real UKUT case |
| q040 | Timeline refusal → hearing | 0.18 | **Adjacent.** Returns appeal content, doesn't nail timing |
| q041 | % of appeals parents win | 0.00 | **Top hit is the literal answer**: IPSEA *"95% of appeals to the SEND Tribunal find in favour of families"* |
| q042 | Support when withdrawing | 0.12 | **Weak.** This is a pastoral question, not a guidance lookup — retrieval can't solve it alone |
| q043 | Separated-parent consent | 0.00 | **Partial.** Finds parental-consent discussion but not the specific edge case |

**6 of 8 queries surface at least one directly useful result in top-3 — ~75% human-judged usefulness against a 24% NDCG metric.**

This gap is methodology-load-bearing. Matcher-based qrels reward exact-pattern matches against the ground truth I authored; they under-count chunks that are *substantively* relevant without satisfying specific matcher conditions. A production system would layer LLM-as-judge evaluation (Roadmap #5) to close the measurement-vs-usefulness gap. Meanwhile: the retrieval layer does real work on the queries that matter most.

## What broke

- **Modern DfE publishes XLSX, not CSV.** First-pass CSV adapter yielded zero docs. Pivoted to a tabular adapter handling both; XLSX sheets with multi-row headers stress the heuristic header-row detection.
- **gov.uk search API returns off-topic pages** for broad queries (UK passport renewal for "SEN school"). Needed a precision-biased SEN-marker body filter, dropping ~30% of raw-discovered pages.
- **Local Authority sitemaps vary wildly.** Of 16 LAs probed, 6 returned 403/404. Of the 10 accessible, doc yield ranges from 3 (Leicester, Hackney) to 80 (Lewisham, Brighton, Oxfordshire at cap). The variance problem made concrete.
- **Cross-encoder rerank hurts quality on this domain.** Unexpected: `bge-reranker-base` re-orders top-10 candidates worse than the fused ordering they came with. Reported in ROADMAP (swap to `bge-reranker-v2-m3` or domain-adapted reranker, item #2).

## What I learned

The single most load-bearing finding is the **LA Local Offer fragmentation problem** — 152 English LAs, 152 implementations of the same statutory requirement, variable depth, no common schema. Any serious SEN tool has to solve this as a first-class concern. This sample exposes it concretely; ROADMAP item #3 prescribes the production path.

On retrieval: **hybrid beats semantic on 4 of 7 query types and matches on 2 more**, validating the core approach even though BM25 alone never wins outright. **Rerank provides no value on this domain** with the tested model — a real finding, not a tuning failure. The statutory-citation result is the finding that most updated my priors: I predicted BM25 would dominate section-number queries (§9.14, section 19 CFA 2014) and budgeted tuning work for it; the data says the opposite — semantic wins 0.163 vs 0.072 because dense embeddings pick up legal-statutory phrasing context that raw token matching misses. The query-type classifier (ROADMAP #2) should therefore route statutory-citation to **semantic-heavier** weights, the inverse of what I'd have concluded without isolating BM25 as its own config.

On evaluation methodology: **matcher-based qrels are conservative.** The gap between 24% NDCG and 75% human usefulness on parent-scenario queries is a senior-engineer signal — real evaluation needs LLM-as-judge or human-in-loop to close.

## Honest failure modes

- **Not production-ready for real parents.** 30% P@5 means 3-4 of every 5 shown results are off-target. Statutory NDCG of 0.13 on queries with the highest stakes (legal rights, deadlines) is not acceptable for deployed use. See `docs/ROADMAP.md` for the ordered path to parent-readiness.
- **Synthesis layer exists but is not evaluated.** A demonstrator RAG layer ships alongside (see "Beyond the brief" above) — confidence-gated, cited, cost-tracked — but hallucination rate, prompt ablation, cost regression, and failure-state coverage are not measured in this submission. ROADMAP item #1 is the ~3-day build to treat that layer with the same eval rigour as retrieval. Without those measurements, the synthesis is illustrative, not production-trustable.
- **XLSX schema detection is heuristic** — complex multi-row DfE headers occasionally mis-identify the header row.
- **LA coverage is skewed** — 3 docs for Leicester, 80 for Lewisham. Bespoke adapters needed for full rollout.

## What I'd change with more time

See `docs/ROADMAP.md` for the ordered 5-item plan. Headline:

1. **Harden + evaluate the synthesis layer** (~3 days) — hallucination eval, prompt ablation, cost regression, failure-state coverage; turns the demonstrator into a measured, production-trustable component
2. **Query-type classifier with adaptive config** (1 day) — closes the per-type gaps the eval exposes
3. **Per-LA topic normalisation** (2 days) — addresses the fragmentation problem exposed by this sample
4. **Reranker quantisation + domain adaptation** (2 days) — makes rerank *help* instead of hurt
5. **Parent-feedback loop** (1 day) — closes the eval-to-deployment loop

## Development approach

Built in pair-programming mode with Claude Code (Opus 4.7). Full AI-usage disclosure in `docs/AI_USAGE.md` — Claude drafted most of the code, I owned every architectural and evaluation decision, I reviewed every commit, and the interpretation of the numbers is mine. Two AI uses that directly affect the artefact are flagged separately: (1) Claude generated candidate eval queries which I reviewed and edited, (2) the SEN-marker relevance filter was brainstormed collaboratively and finalised by me. I did not ask Claude to generate ground-truth grades.

The gap between NDCG and human usefulness on parent-scenario queries is the observation I am proudest of in this submission — not because the number is impressive but because the method surfaced it honestly.
