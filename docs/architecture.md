# Architecture Decisions

This document explains the architectural choices behind the retrieval
platform, the alternatives considered, and the trade-offs taken. It is
written for a reviewer evaluating engineering judgment — the *why* sits
alongside the *what*.

## 1. System overview

```
                        ┌──────────────────┐
                        │  POST /search    │
                        │  (FastAPI)       │
                        └────────┬─────────┘
                                 │
                ┌────────────────┴────────────────┐
                │       SearchService             │
                │  ┌───────────┬──────────────┐   │
                │  │  semantic │ hybrid       │   │
                │  │           │ hybrid+rerank│   │
                │  └───────────┴──────────────┘   │
                └────────────────┬────────────────┘
                                 │
      ┌──────────────────────────┼──────────────────────────┐
      ▼                          ▼                          ▼
 ┌─────────┐              ┌──────────┐              ┌────────────┐
 │  BM25   │              │  Dense   │              │  Cross-    │
 │ (bm25s) │              │  (BGE +  │              │  encoder   │
 │  index  │              │  Qdrant) │              │  reranker  │
 └─────────┘              └──────────┘              └────────────┘
      ▲                          ▲
      │                          │
      └─────── chunks JSONL ─────┘
                    ▲
                    │
              ┌─────┴──────┐
              │  Ingest    │
              │  pipeline  │
              └─────┬──────┘
                    │
    ┌──────┬────────┼────────┬──────────┬──────────┐
    ▼      ▼        ▼        ▼          ▼          ▼
 SEND   gov.uk   DfE       LA         IPSEA     Contact
 CoP    SEND     stats     Local Offer
 (PDF)  pages    (XLSX)    (HTML)
```

Four layers, each independently testable:

1. **Ingest** — source-specific adapters produce `Document` objects; a
   heading-boundary chunker emits `Chunk` objects with stable hashes.
2. **Indexing** — BM25 (pure-Python) + dense (BGE embeddings in Qdrant);
   both consume the same chunks JSONL.
3. **Retrieval** — three composable configurations with tunable weights
   and optional cross-encoder rerank; common `SearchResult` shape.
4. **API** — FastAPI over the retrieval layer, with structured logging
   and Prometheus metrics.

## 2. Technology choices + rationale

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11 | Most-cited tools in the space (sentence-transformers, Qdrant client, bm25s) are Python-first. 3.11 gives us clean union syntax and faster stdlib. |
| Vector DB | **Qdrant** (docker-compose) | Production-grade, native metadata filtering (open-schema), HNSW index, ~30s to run locally. Reviewer reproducibility is the constraint. |
| Embedding model | **`BAAI/bge-large-en-v1.5`** (1024-dim) | Strong BEIR scores, open weights, runs on CPU, no API key. |
| BM25 | **`bm25s`** (pure Python) | Fast (~100× faster than rank-bm25 on our corpus), no Java runtime, easy to reason about. |
| Cross-encoder | **`BAAI/bge-reranker-base`** | Small (~280M params), CPU-friendly, well-benchmarked. |
| API | **FastAPI + uvicorn** | Type-hinted, automatic OpenAPI, standard ASGI. |
| PDF parsing | **`pypdf` + `pdfplumber`** | Well-known, no LLM-based parsing keeps the pipeline deterministic and reviewer-reproducible. |
| Spreadsheet parsing | **`openpyxl`** | Modern DfE SEN statistics are published as XLSX, not CSV; `openpyxl` is the reference library. |
| HTML parsing | **`beautifulsoup4` + `lxml`** | Lenient parser for real-world government and charity HTML. |
| Observability | **`prometheus-fastapi-instrumentator` + `structlog`** | Standard HTTP metrics plus custom counters for config/latency/rerank; JSON logs with `query_id` correlation. |

## 3. Rejected alternatives

| Considered | Rejected because |
|---|---|
| **OpenSearch + Bedrock Titan** | Heavier for a reviewer to run; requires AWS credentials. Genuine production choice for a larger deployment, but wrong trade-off for a 3-day take-home that must be reproducible in 10 minutes on a laptop. |
| **LlamaIndex** | Obscures the architectural decisions the assessment is asking us to defend. Composing BM25 + dense + rerank ourselves makes the trade-offs explicit in code. |
| **Haystack 2.x** | Same concern as LlamaIndex; also heavier install. |
| **Elasticsearch** | Java runtime; slower reviewer onboarding. |
| **Chroma** | Less expressive metadata filtering than Qdrant; fewer production-grade operational signals. |
| **DuckDB + VSS** | Zero-infra appeal, but no native BM25; VSS is immature for hybrid relative to Qdrant. |
| **pgvector** | Requires Postgres + extension setup; same concern as Elasticsearch for reviewer onboarding. |
| **OpenAI / Cohere embeddings** | API-key friction for reviewer; cost; less reproducible. |
| **Claude/GPT as the reranker** | Per-query cost and latency blow the <500ms budget; 1000× more expensive than a local cross-encoder. |
| **Row-per-CSV as a document** | Thousands of semantically-thin atoms. Opted for one Document per CSV/XLSX sheet with a text description (title, schema, row count, sample rows) — each sheet becomes a retrievable knowledge unit. |

## 4. Data pipeline

**Incremental re-ingest.** Source adapters cache fetched content to disk
(`data/cache/<source>/`) keyed by stable URL-derived names. Re-running
skips the network request if the cache hit is valid.

**Chunking.** Three strategies implemented:

- `FixedSizeChunker` — structure-blind baseline, fixed char window with
  overlap.
- `HeadingBoundaryChunker` — respects detected section structure; splits
  oversize sections with overlap; falls back to fixed when a document
  carries no structure.
- *Parent-child chunker is deferred to the "what I'd ship next" list.*

A chunker's config is content-hashed (`hash_config`) — the hash becomes
part of the chunks JSONL filename, so different chunkers land in
different files and can be compared side-by-side without cross-contamination.

**Stable identifiers.**
`doc_id = <source>::<hash(source_id)>` — stable across ingest runs.
`chunk_id = <doc_id>::<seq>[::<section_ref>]` — stable across chunker
reruns if text is unchanged; different if text or chunker config changes.

**Open-schema metadata.** Every chunk carries a `metadata: Dict[str, Any]`
that absorbs source-specific fields without schema migration:
`local_authority`, `region`, `doc_type`, `charity`, `format`,
`publication_year`, etc. The `/search` API's `filters` argument maps
directly onto this dict.

### Why file-based storage (no SQL DB for chunks)

Chunks are persisted as JSONL (one file per chunker-config hash) and
documents as individual JSON files. No SQLite, no Postgres, no
MongoDB. That's a deliberate choice at this corpus size (~1.2K docs,
~8.7K chunks):

- **The dense index is already a DB** — Qdrant stores vectors and
  payload metadata with a proper index. Metadata filtering
  (`local_authority`, `source`, date ranges, custom tags) goes through
  Qdrant, which is where it belongs.
- **BM25 needs the full chunk text in process memory anyway** (bm25s
  design). A DB fetch wouldn't save that cost.
- **No concurrent writers** during ingest; single-writer semantics are
  already satisfied by file rewrite.
- **Reviewer reproducibility** — files are inspectable with `jq`, `grep`,
  and `cat`; no DB setup step in the README.

A production rollout to 100K+ documents or with multiple concurrent
writers would move chunk metadata to SQLite (single-file, zero-infra,
upsertable) or Postgres. That migration is captured in `docs/ROADMAP.md`
under production-scale concerns. At this scale, adding a DB costs
complexity and gains nothing measurable.

## 5. Retrieval pipeline

Four configurations share the same `SearchResult` shape so the eval
harness (and the API caller) can treat them uniformly:

| Config | Retrievers | Fusion | Rerank | Target latency |
|---|---|---|---|---|
| `bm25` | BM25 only (lexical baseline) | n/a | no | <10ms |
| `semantic` | dense only | n/a | no | <200ms |
| `hybrid` | BM25 + dense | weighted-normalised-sum (default) or RRF | no | <200ms |
| `hybrid_rerank` | BM25 + dense | weighted / RRF | cross-encoder over top-50 | <500ms |

The `bm25` config exists as its own first-class endpoint so that the
eval harness can answer *"when does BM25 beat semantic?"* directly
rather than having to infer it from hybrid-minus-semantic deltas.

**Weighted fusion.** Each retriever's scores are min-max normalised to
[0,1] then summed with tunable weights (default 0.35 BM25, 0.65 dense).
Normalisation handles the scale difference — BM25 raw scores run in the
tens or hundreds; cosine similarity is 0-1 — and produces comparable
contributions in the score breakdown returned to the caller.

**RRF alternative.** Reciprocal Rank Fusion is parameter-free and robust
to scale differences; exposed as an alternative fusion mode for cases
where weight tuning is unwarranted.

**Cross-encoder rerank.** Top-50 fused candidates are scored by
`(query, candidate.text)` cross-encoder predictions; results are
returned ordered by rerank score. The reranker is loaded lazily on first
invocation to keep startup fast.

**Score breakdown.** Every `/search` result carries per-retriever
scores: `{bm25, semantic, reranker, fused}`. This is (a) an eval
debugging aid, (b) a transparency property for the eventual answer-
generation layer to cite confident vs borderline retrievals.

## 6. Evaluation methodology

**Graded queries + matcher-based qrels.** Queries are authored in
`eval/queries.yaml` with ground-truth *matchers* — open-schema dicts
against chunk metadata (`source`, `section_ref`, `local_authority`,
`charity`, `text_contains`, ...) with graded relevance (0, 1, 2). At
eval time the harness scans the corpus against each matcher and builds
per-query qrels (chunk_id → grade). This is more robust than listing
specific chunk IDs — if the chunker config changes, the matchers still
select the right chunks without manual re-authoring.

**Metrics.** Precision@5, Recall@5, NDCG@5 — implemented directly rather
than via `ranx` so there is exactly one source of truth for what is
being measured. NDCG uses the `(2^rel - 1)` gain function with
`log2(rank + 1)` position discount.

**Configurations compared.** All four retrieval configs (`bm25`,
`semantic`, `hybrid`, `hybrid_rerank`) are evaluated on every query;
results are reported side-by-side with a per-query-type breakdown.
Latency distribution (p50, p95) is captured per config.

*See the Evaluation Results section of the main README for numbers.*

## 7. Performance characteristics

**Latency budget (p95 < 500ms).**

| Stage | Budget | Strategy |
|---|---|---|
| Query embed | 30ms | Warm model; single-query batch |
| BM25 retrieve top-100 | 20ms | In-memory bm25s |
| Dense retrieve top-100 | 80ms | Qdrant HNSW |
| Fuse + dedupe | 5ms | Python |
| Rerank top-50 | 300ms | `bge-reranker-base` CPU; see "what's next" for quantisation |
| Metadata filter + response | 10ms | Pre-filter in Qdrant |
| **Total** | **445ms** | 55ms headroom |

If the reranker blows the budget on a given machine, callers can
select `config=hybrid` (no rerank) and stay <200ms p95.

**Cost per 1,000 queries.** All models are local/open — there is no
per-query API cost. Dominant cost is one-time embedding of the corpus
(measured in the eval run and reported in the results).

**Cold vs warm cache.** Reported in the eval output — first queries
after process startup pay model-load latency; steady-state is
reported separately.

## 8. Trade-offs summary

| Trade-off | Chosen | Alternative | Reason |
|---|---|---|---|
| Reviewer reproducibility vs. production parity | Local open models + Qdrant | Bedrock Titan + OpenSearch | 10-minute laptop setup > AWS account |
| Framework vs. explicit composition | Explicit (own code) | LlamaIndex / Haystack | Make decisions visible |
| Transparent metrics vs. ranx | Direct implementation | ranx library | Fewer layers of abstraction between code and claims |
| Multi-row vs. single-doc per CSV | Single doc with text description | Row-per-chunk | Semantic coherence of the unit retrieved |
| XLSX-as-CSV | Handled as tabular data | Strict CSV-only | Modern DfE publishes XLSX; spirit of the spec is "tabular data" |
| Broad LA coverage vs. depth | 15 LAs sampled, variable depth | Deep coverage of 3 LAs | Demonstrates the 152-LA variance problem — the real-world differentiator |
| Relevance filter precision vs. recall | Precision-forward | Broad recall | Tight SEN-markers set beats broad-match; off-topic pages kill evaluation quality |

## 9. Beyond the core: synthesis layer (not evaluated)

A small RAG synthesis layer and a minimal web chat UI ship alongside
the graded retrieval platform — built as a personal demonstrator to
show the retrieval is load-bearing for a real parent-facing product,
not evaluated as part of this submission. Called out separately from
the core architecture because none of it contributes to the retrieval
numbers in the REPORT.

**Layout.**

```
          ┌───────────────────────┐
          │  POST /chat           │  minimal web chat UI
          │  (FastAPI + HTML)     │
          └──────────┬────────────┘
                     │
          ┌──────────▼────────────┐
          │  RagSynthesizer       │
          │   · confidence gate   │──── below threshold → IPSEA escalation
          │   · provider select   │
          │   · citation builder  │
          │   · GBP cost tracker  │
          └──────────┬────────────┘
                     │
      ┌──────────────┴──────────────┐
      ▼                             ▼
┌──────────────┐              ┌──────────────┐
│  Anthropic   │              │  z.ai GLM    │
│   Claude     │              │ (OpenAI-     │
│   (Sonnet)   │              │  compatible) │
└──────────────┘              └──────────────┘
```

**Design choices.**

| Concern | Choice | Why |
|---|---|---|
| Provider abstraction | Minimal `_Provider` base → `_AnthropicProvider` + `_ZaiProvider` | Keeps switching provider to an env-var change — no code path divergence at call sites. |
| Provider selection | Startup, via env vars, Anthropic preferred | Deterministic; fail-loud if none set rather than silently degrading. |
| z.ai endpoint | `/api/coding/paas/v4` default | z.ai splits pay-per-call from the coding plan; coding-plan endpoint is what a subscribed account has balance on. |
| Confidence gate | Fused score < 0.30 → skip LLM, return IPSEA escalation | Saves cost; avoids hallucination on weak retrievals; surfaces the system's epistemic limit rather than hiding it. |
| Response states | `high` / `medium` / `low` / `llm_error` / `out_of_scope` | `llm_error` distinct from `low` — when the LLM call fails, retrieval still worked, so citations survive and the UI shows sources. |
| Citations | Numbered `[1]`, `[2]`, tied to chunk_id + source + section_ref | Every factual claim must be citable; the citation payload is what the UI renders as expandable source panels. |
| Cost tracking | Per-call token × provider rate, GBP | Observable on every request; feeds the eventual cost-regression check (ROADMAP #1). |
| Disclaimer | Fixed text appended to every high/medium answer | "Information, not legal advice" — non-negotiable for SEN. |

**What's deliberately missing — deferred to ROADMAP #1:**

- Hallucination eval (no held-out claim-support tests)
- Prompt ablation (no measurement of which prompt elements earn their place)
- Cost regression wired into CI
- Failure-state test coverage beyond smoke tests
- Provider-parity measurement (Anthropic vs z.ai on the same corpus)

The layer works; it is not yet *measured* to the standard the retrieval layer is. That gap is explicit.

## 10. What's next

See `docs/ROADMAP.md` ("What I'd ship next week") for the prioritised
list. Highlights:

- Query-type classifier that routes to different retrieval configs
  adaptively.
- Quantised reranker for sub-200ms `hybrid_rerank`.
- Per-source incremental re-embed check (hash compare on the source
  document level, not just the network cache).
- Harden + evaluate the synthesis layer (hallucination eval, prompt
  ablation, cost regression, failure-state coverage) — the
  demonstrator exists; the eval rigour does not, yet.
- Per-LA normalisation classifier to surface equivalent guidance
  across 152 LAs.
