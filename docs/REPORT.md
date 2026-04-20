# Report — Retrieval Platform over UK SEN Guidance

*~2 pages. Final numbers inserted from the eval run on the day of
submission.*

## What I built

A hybrid retrieval platform over 1,215 documents of UK Special
Educational Needs guidance (8,691 chunks, 6.6 MB text). The corpus
covers all three document types the brief asks for: PDF (SEND Code of
Practice, DfE publications), HTML (gov.uk SEND pages, 15 Local
Authority Local Offers, IPSEA, Contact), and tabular data (113 DfE
statistics workbooks — modern DfE publishes XLSX where the brief says
"CSV"; XLSX sheets are handled as first-class tabular documents).

Retrieval composes BM25 (`bm25s`) + dense embeddings
(`BAAI/bge-large-en-v1.5`, stored in Qdrant) + cross-encoder rerank
(`BAAI/bge-reranker-base`), with tunable fusion weights and an
alternate RRF mode. Three composable configurations are exposed via
`POST /search`: `semantic` (dense only), `hybrid` (fused), and
`hybrid_rerank` (fused + reranked). Each result carries a score
breakdown per retriever, so the caller sees *why* a chunk ranked where
it did.

The API is FastAPI with `/metrics` (Prometheus) and structured JSON
logs with `query_id` correlation. An async load-test CLI reports
throughput and latency percentiles under concurrent pressure.

Ingest is source-plug-in: six adapters implementing a 3-method
`SourceAdapter` interface. Re-runs are incremental at the network
cache level (HTTP fetches skip if cached); chunker-config changes are
hashed into chunk filenames so different strategies can be compared
without contamination.

## Results

*(Final numbers from `eval_runs/` — see the full eval report committed
alongside this one.)*

| Config | P@5 | R@5 | NDCG@5 | p50 latency | p95 latency |
|---|---|---|---|---|---|
| `semantic` | _TBD_ | _TBD_ | _TBD_ | _TBD_ ms | _TBD_ ms |
| `hybrid` | _TBD_ | _TBD_ | _TBD_ | _TBD_ ms | _TBD_ ms |
| `hybrid_rerank` | _TBD_ | _TBD_ | _TBD_ | _TBD_ ms | _TBD_ ms |

Across **35 graded queries** spanning statutory citation,
symptom-driven, process, timing, rights/refusal, and out-of-scope
types. Ground truth authored manually with open-schema matchers
(source + section-ref + text-anchor) rather than hard-coded chunk IDs,
so chunker changes don't break the eval set.

### Per-query-type NDCG@5

*(inserted from eval output)*

### Cold vs warm cache latency

First query after service startup: _TBD_ ms (model warm-up).
Steady-state p95 from query 10 onwards: _TBD_ ms.

### Concurrency

Load test at 20 concurrent clients against `hybrid_rerank`:
throughput _TBD_ req/s · p95 _TBD_ ms · error rate _TBD_%.

### Cost per 1,000 queries

All models local/open — per-query API cost is **£0.00**. Dominant
cost is one-time embedding of the corpus: _TBD_ CPU-minutes on
developer hardware.

## What broke

- **DfE CSVs don't exist anymore.** Modern DfE publications (post
  ~2022) ship XLSX attachments, not CSVs, and the EES data portal
  uses JS-loaded API downloads I couldn't discover quickly. First-pass
  CSV adapter yielded zero docs. Pivoted to a tabular-data adapter
  handling both formats, with XLSX sheets becoming separate documents.
  XLSX has multi-row headers that my heuristic doesn't fully detect;
  the body text is still retrievable but the schema description is
  occasionally messy. Noted in the arch doc.
- **gov.uk search API returns genuinely off-topic results** for broad
  SEN queries — UK passport renewal appeared for "SEN school" before
  relevance filtering. Needed a precision-biased body-content SEN-marker
  check to keep the corpus clean. Removed ~30% of raw-discovered pages.
- **Local Authority sitemaps vary wildly** — 6 of 16 probed LAs
  returned 403/404 on `/sitemap.xml` (Camden, Cornwall, Kent,
  Hampshire, …). Of the 15 that yielded content, coverage ranges from
  3 docs (Leicester, Hackney) to 80 docs (Lewisham, Brighton,
  Oxfordshire). This *is* the Local Offer variance problem in
  miniature and is the main "what's next" item.

## What I learned

The most load-bearing finding is that **LA Local Offer fragmentation
is real and severe**. Same statutory requirement, 152 English LAs,
dozens of different CMS platforms, wildly different coverage depth.
Any serious SEN knowledge tool has to solve the normalisation
problem as a first-class concern, not a polish item.

On the retrieval side, **BM25 matters more for statutory citations
than for anything else**. Parent-language queries ("my child with
autism is being excluded") are dense-semantic-wins territory; queries
anchored in specific section numbers ("Section 19 of the Children
and Families Act") want BM25's exact-term sensitivity. The
per-query-type breakdown in the eval shows this — and it's why
Roadmap item #2 (query-type classifier with adaptive config) is
higher priority than tuning the reranker.

Less expected: **pypdf + regex for section detection on SEND CoP
works better than I anticipated**. 947 numbered statutory sections
recovered cleanly from a 292-page PDF, each usable as a citation
anchor. The heading-boundary chunker respects these and produces
chunks that carry their section reference into the API response —
which is the basis for answer-generation citations in the roadmap.

## Honest failure modes

- **Out-of-scope queries don't score zero** — they score low, but the
  retrieval layer always returns 5 results. Out-of-scope detection
  lives in the future answer-generation layer (item #1 in Roadmap),
  not in retrieval itself. A well-behaved system would return "I
  couldn't find specific guidance on this"; current behaviour shows
  chunks with low fused scores. Caller's responsibility to check
  score confidence.
- **XLSX schema detection is heuristic**. For complex multi-row
  headers in DfE statistics, we sometimes pick the wrong row as
  "header" and the body's "sample rows" lose structure. The body
  text is still retrievable via semantic search (a query for
  "EHCPs by local authority" still hits the right doc) — but the
  sample rows in the description are less parseable than they should
  be. Fix: ship a proper table-structure detector or use a tabular
  LLM at ingest.
- **LA coverage is skewed.** Three LAs at cap (80), three below 10.
  For a parent in Leicester, we have 3 LA-specific docs. The arch
  doc documents this; in production, bespoke per-LA adapters for the
  unusual platforms would close the gap.
- **No answer generation yet.** By design (Assignment 1 is retrieval,
  not RAG-with-generation), but it means this is *not* a
  parent-ready tool. It is the retrieval backbone for one.

## What I'd change with more time

See `docs/ROADMAP.md` for the ordered list. Headline:

1. Answer-generation layer with inline citations (2 days) — turns
   retrieval into a parent-usable tool.
2. Query-type classifier with adaptive retrieval config (1 day) —
   closes the per-type quality gaps the eval shows.
3. Per-LA topic-normalisation pass (2 days) — addresses the variance
   problem that this sample exposes.

## Development approach

Built in pair-programming mode with Claude Code (Opus 4.7). Full
AI-usage disclosure is in `docs/AI_USAGE.md` — which parts Claude
wrote, which parts I owned, and which AI uses affect the artefact.
The short version: Claude wrote most of the code, I made every
architectural and evaluation-methodology decision, I reviewed every
commit, and the interpretation of the eval numbers is mine.
