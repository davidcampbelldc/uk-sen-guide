# What I'd Ship Next Week

A concrete roadmap if I had one more focused week after this delivery.
Five features, ordered by impact-per-engineering-day, with the reasoning
for each. Every item is genuinely sized in days, not hand-waved; I'd
tackle them in the order shown.

## 1. Answer-generation layer with inline citations (~2 days)

The retrieval API returns ranked chunks with source metadata. Parents
using this for real don't want chunk lists — they want an answer with
citations. A thin generation layer on top of retrieval:

- Takes the top-5 retrieved chunks and synthesises a natural-language
  answer with **inline citations** to specific `section_ref` / doc_id.
- Preserves the retrieval layer as standalone (already the intent — the
  generation layer is a wrapping step, not a rewrite).
- Honest about confidence: if top scores are low, returns "I couldn't
  find specific guidance on this" rather than hallucinating.
- Cost-controlled: gated by per-query token budget; falls back to
  "return retrieved chunks" when budget exceeded.

**Why this first:** the retrieval quality the eval validates is only
useful to a parent if it surfaces as an answer. Every other feature on
this list assumes this layer exists.

## 2. Query-type classifier with adaptive retrieval config (~1 day)

The eval shows different retrieval configs win on different query
types (BM25 weight matters more on statutory citations; semantic
dominates symptom-driven queries; rerank buys little on out-of-scope).
A small classifier — either rules-based on query surface features, or
a small fine-tuned model — that routes each query to the right config:

- Route statutory-citation queries to hybrid with BM25 weight bumped.
- Route symptom-driven queries to hybrid_rerank with rerank weight
  bumped.
- Detect out-of-scope queries and short-circuit to a "no specific
  guidance found" response without calling the reranker.

**Why second:** this is the highest-leverage tuning we can do — takes
our *already-measured* per-type quality gaps and closes them without
touching the retrieval code itself. It's a routing layer, not a model
change.

## 3. Per-LA topic-normalisation pass at ingest time (~2 days)

The corpus includes 15 Local Authorities with variable coverage (3 to
80 docs each, heavily skewed). Behind the variance is a taxonomy of
topics (EHCP application, transport, respite, post-16 transition,
mediation) that every LA covers, each in their own words, with
different emphasis and structure.

- At ingest, run each LA page through a small classifier that tags
  topics from a shared taxonomy.
- Expose the taxonomy as filterable metadata: `topic=ehcp-process`,
  `topic=transport`, `topic=post-16-transition`.
- Surface coverage gaps: for every `(LA × topic)` cell, flag which are
  empty. A parent query filtered to their LA + topic can then say
  *"your LA hasn't published on this — here's national guidance
  instead"*.

**Why third:** the LA variance problem is the single most-concrete
real-world differentiator of a SEN knowledge tool. National guidance is
widely available; LA-specific guidance is fragmented. Fixing this
fragmentation is the product value-add for eventual rollout.

## 4. Reranker quantisation + rerank-aware config tuning (~2 days)

The current `hybrid_rerank` config fits within the 500ms p95 budget but
uses most of it (measured in eval: ~300ms for the reranker alone on
CPU). Two improvements:

- **Quantise the cross-encoder** using `optimum` / `onnxruntime` to
  INT8 — expected ~3× speedup on CPU with <1% quality degradation on
  our graded eval. Target: rerank phase <100ms.
- **Rerank-aware config tuning** — with faster rerank, we can rerank a
  larger candidate pool (top-100 instead of top-50) and see if NDCG
  improves without blowing the latency budget.

**Why fourth:** makes `hybrid_rerank` viable as the default config at
parent-facing latency. Also directly enables item #1 (answer generation)
to use better candidates without adding latency.

## 5. Parent-feedback loop for ranking signal (~1 day)

The API already emits a `query_id` per request. Extending this into a
feedback signal:

- New endpoint `POST /feedback` accepting `{query_id, chunk_id, signal}`
  where `signal ∈ {helpful, not-helpful, incorrect}`.
- Structured logs capture (query, result shown, signal) triples.
- Export as training data for a fine-tuned reranker (item for the
  week after). In the short term: use it to detect *systematic*
  problems — queries where top-5 consistently gets downvoted are the
  ones we re-author in the eval set.

**Why fifth:** closing the loop between deployment and eval. Without
this, the eval quality is a snapshot; with it, the system improves from
real usage. One day of work unlocks a continuous-improvement flywheel.

---

## Out of scope for "next week"

These would be great, but don't fit a single week:

- **UI for parents.** Non-trivial. Needs design, auth, accessibility,
  safeguarding disclaimers, content warnings on sensitive topics
  (mental health, exclusions). Weeks of work, not days.
- **Per-source freshness heartbeat.** LAs update guidance irregularly;
  we'd need a monthly background job with per-source change detection.
  Worthy but not blocking.
- **Multi-tenancy and EHCP privacy.** Would let parents upload their
  own EHCPs for personalised retrieval. Significant scope: tenant
  isolation, encryption at rest, GDPR DPIA.
- **Welsh / Scottish / Northern Irish frameworks.** Different statutory
  regimes, different LAs, different charities. Material duplication of
  the current pipeline.
- **Case law ingestion.** SEND Tribunal decisions carry precedent
  value; ingestion + redaction would open new query types but is a
  specialised sub-project.

---

## What the eval tells me about priority

The observed quality gap by query type (from the eval run in
`eval_runs/`) informs the order above. Items 1 and 3 target the
queries we score weakest on; items 2 and 4 improve the configs that
*don't* win. If the eval surfaced a different weakness — for example,
if cold-cache latency dominated rather than steady-state — item 4 would
move earlier.
