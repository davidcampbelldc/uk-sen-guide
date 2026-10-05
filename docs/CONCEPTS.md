---
title: "Key Concepts and Architectural Decisions of an SEN Information Search System, Explained in Plain English"
date: 2026-04-21
status: PARTIAL
question: "What problem does this SEN search system solve, and how do its ingestion, chunking and indexing stages work in plain English?"
topic: docs
backfilled: 2026-10-05
---

# Key Concepts and Architectural Decisions — In Plain English

A gentler companion to `docs/architecture.md` and `docs/REPORT.md`. Same content, less jargon, designed to be readable by someone who doesn't build search systems for a living. Every technical term is either explained here or cross-referenced in `docs/GLOSSARY.md`.

If you want the terse expert-level version, go to `architecture.md`. If you want a term defined, go to `GLOSSARY.md`. This doc is the *why-does-this-look-the-way-it-does* walk-through.

---

## 1. What problem is this system solving?

Parents of children with Special Educational Needs (SEN) face a genuinely hostile information landscape. The material they need is:

- **Real** — statutory guidance (the SEND Code of Practice), legislation (the Children and Families Act 2014), Tribunal case decisions, gov.uk explanations, council-specific support catalogues, and charity walkthroughs.
- **Fragmented** — 152 local authorities in England each publish their own version of the same statutory duties, with wildly different formats and depths.
- **Adversarial** — Tribunal statistics show 95% of appeals find in favour of families. That tells you something about the quality of the decisions families are appealing against.
- **Urgent** — often being read under real pressure, by a parent preparing for an assessment or a hearing.

A good search layer over this material is a load-bearing piece of any tool that wants to help parents navigate the system honestly. This project is that search layer.

---

## 2. How does the system actually work?

From the outside: you send it a question, it returns the five most relevant passages from the corpus, with citations back to the original documents.

Under the hood, four stages:

### Stage 1 — Ingest (getting documents in)

Source-specific adapters fetch each document type:
- PDFs (the SEND Code of Practice) are parsed into sections by spotting numbered headings like "9.14".
- HTML pages (gov.uk, councils, IPSEA, Contact) are stripped of navigation and reduced to their main content.
- Excel spreadsheets (DfE statistics) are turned into one-document-per-sheet with a plain-English description.
- Fetched content is cached on disk so rerunning doesn't re-hit the network.

Total pulled in: 1,215 documents.

### Stage 2 — Chunking (breaking them up)

An 800-page PDF is unusable as a single search result. Documents are split into smaller searchable *chunks* (typically paragraph or section-sized). Two strategies are implemented so they can be compared:

- **Fixed-size** — splits every N characters. Simple, structure-blind, serves as a baseline.
- **Heading-boundary** — splits on detected section headings. Preserves the "§9.14" citation anchors that make statutory content usable.

The default is heading-boundary because preserving section references matters for statutory material. 91% of chunks keep their section anchor that way.

Total: 8,691 chunks.

### Stage 3 — Indexing (building two indices)

Each chunk is indexed in two different ways:

- **BM25 index** — a keyword index. Given a query, returns chunks that share words with it, weighted by how rare those words are in the corpus overall.
- **Dense index** (in Qdrant) — a semantic index. An AI model (BGE-large) reads each chunk and produces a 1024-number "meaning-fingerprint" (called a *dense embedding*). Given a query, the model produces a fingerprint for the query too, and the system returns chunks whose fingerprints are geometrically close.

Both indices cover the same 8,691 chunks.

### Stage 4 — Retrieval (answering queries)

Four search configurations are exposed. All take a query and return the top-5 passages:

- **`bm25`** — keyword only (fast, free, no meaning awareness).
- **`semantic`** — dense embeddings only (slower, requires an AI model, matches on meaning).
- **`hybrid`** — both of the above, with scores blended via tunable weights.
- **`hybrid_rerank`** — hybrid first, then a second AI model (a *cross-encoder reranker*) re-reads the top 50 and re-sorts them.

The choice of which to expose for real-world use depends on a query-type router (a future item) — different types of question benefit from different configurations.

Every result includes a breakdown showing how each layer scored it — so you can see *why* a particular passage ranked where it did.

---

## 3. Why these particular choices?

The repo has a longer `architecture.md` with a rejected-alternatives table. Here's the short version of the big calls:

### Why Qdrant (not a managed cloud service)?
A reviewer opening this repo should be able to run it in 10 minutes on a laptop, without AWS credentials or a Pinecone API key. Qdrant is free, self-hosted in Docker, and production-grade. Losing zero-config-cloud convenience in exchange for zero-credential-friction reviewer experience was the right trade.

### Why BGE-large (not paid embedding APIs like OpenAI or Cohere)?
Same reason. Open weights, CPU-runnable, no API key needed. Strong on standard benchmarks. Costs nothing per query — which makes the cost-per-1000-queries calculations honest.

### Why no LlamaIndex, Haystack, or similar framework?
Frameworks are time-savers when you want the framework's opinions. Here, *defending the retrieval decisions* is exactly the work. Building BM25 + dense + rerank + fusion explicitly in my own code means every design choice is visible, reviewable, and mine to justify. Less slick, more honest.

### Why treat Excel spreadsheets as one-document-per-sheet (not one-row-per-document)?
The DfE publishes its SEN statistics in XLSX workbooks — Special Educational Needs by age, by region, by year. A row in one of those sheets is typically "Westminster, Year 10, 2023, 157 children" — semantically thin on its own. The useful unit of retrieval is *the sheet*, with a plain-English description of what it contains. Each sheet becomes one document carrying its title, schema, and some sample rows.

### Why implement my own evaluation metrics instead of using `ranx`?
Same theme. Precision@5, Recall@5, NDCG@5 — these are well-defined enough that wrapping them in a library adds a layer of "the library did it" between the code and the claims. Writing them directly means there's one source of truth for what every percentage point actually measures.

### Why 43 hand-authored queries instead of a standard test set?
Because there isn't a standard test set for UK SEN retrieval — the whole reason this corpus is interesting. I wrote every query; I wrote every ground-truth matcher; I authored the eight real-parent-scenario queries from lived experience (anonymised). The quality and the limitations of the eval are therefore mine to own.

---

## 4. What "good" looks like, and how I measured it

The brief for any retrieval system is: *when the user asks a question, are the most useful answers in the top 5 results?* Three standard measurements capture this:

- **Precision at 5 (P@5)** — of the 5 returned results, what fraction were actually relevant? Higher = less noise.
- **Recall at 5 (R@5)** — of *all* the relevant passages in the corpus, what fraction did the top 5 capture? With thousands of relevant-ish chunks per query, this is always a small number; the ratio between configurations is what matters.
- **NDCG at 5 (NDCG@5)** — a weighted score on a 0-to-1 scale that rewards *relevant-near-the-top*. Often the single most informative number for search.

Each configuration was scored on all 43 queries. All scores are reproducible from the raw per-query outputs committed under `eval_runs/` — a reviewer can recompute every decimal in 15 lines of Python.

Results (headline):

| Configuration | Precision@5 | Recall@5 | NDCG@5 | Median latency | Slowest 5% latency |
|---|---|---|---|---|---|
| Keyword (BM25) | 0.251 | 0.019 | 0.221 | <1 ms | <1 ms |
| Semantic | 0.298 | 0.023 | 0.267 | 94 ms | 186 ms |
| **Hybrid** | **0.307** | 0.023 | **0.285** | 99 ms | 135 ms |
| Hybrid + rerank | 0.260 | 0.017 | 0.238 | 2,300 ms | 2,408 ms |

Hybrid wins overall. Rerank *hurts* quality on this domain — a real, honest finding that contradicts the usual "more layers = better" intuition.

---

## 5. The one finding that updated my prior

I had a strong opinion going in: *"keyword search will dominate statutory-citation queries — parents searching for '§9.14' should match lexically, and semantic search won't help with a symbol."*

It wasn't so — not by a little but by a factor of two. On statutory-citation queries:

- Keyword-only: NDCG 0.072
- Semantic-only: NDCG **0.163**
- Hybrid: 0.127

Semantic won decisively. The BGE-large embedding model has clearly absorbed a lot of legal-statutory English during training, so *"duties under Section 19 of the Children and Families Act 2014"* is recognised as *about local authority SEN duties* regardless of whether the target document uses that exact reference. Keyword search doesn't read meaning — it just matches words — so it happily returns a DfE publication about Section 19 of *a different Act*.

My follow-on plan (the query-type router, listed in ROADMAP item #2) had me sending statutory queries to a BM25-heavy configuration. That plan is now inverted: statutory queries should go to a semantic-heavier configuration. This kind of prior-update only happens if you isolate the configurations and measure them head-to-head.

---

## 6. A second finding: the gap between "metric" and "usefulness"

Eight of the 43 queries are *real-parent-scenario* questions — anonymised versions of things people actually ask in SEN cases. On those eight, the system scored 0.238 on NDCG@5 — 24%. Sounds bad.

I then read the top-3 results for each by hand and rated them for usefulness. **Six of eight had at least one directly useful result in the top three.** Human-judged usefulness: ~75%.

The measurement is undercounting. That's not a bug — it's a property of matcher-based evaluation: the ground-truth list marks specific passages as "relevant", but retrieval returns substantively useful passages that happen not to be on the exact list.

This is the kind of gap that gets buried in reports showing only the headline number. Naming it and having a plan (LLM-as-judge evaluation, roadmap item) is the senior-engineer move.

---

## 7. Honest failure modes

In order of severity:

1. **Not production-ready for real parents.** 30% precision@5 means 3-4 of every 5 shown results are off-target. For a tool going in front of stressed parents, that's not acceptable without an additional trust layer (confidence gating + escalation).
2. **Rerank makes things worse on this corpus.** The off-the-shelf reranker (`bge-reranker-base`) hurts quality (-0.047 NDCG). Fix: domain-adapted reranker, maybe quantised to run faster. In the roadmap.
3. **Hybrid+rerank breaks the 500ms latency budget.** At 2.3s median, 2.4s for the slowest 5%, it's not usable as a production default. Other configurations are inside budget.
4. **Incremental re-ingest is partial.** Fetching is cached, but re-running the indexer still re-embeds every chunk. Fine at this corpus size; wants work before 100k+ documents.
5. **Local Authority coverage is skewed.** 15 of 152 councils, ranging 3-80 docs each. The variance problem in microcosm.
6. **XLSX schema detection is heuristic.** Some DfE workbooks with multi-row headers confuse the header-row detector.

All of these are in the REPORT's "Honest failure modes" section, not hidden.

---

## 8. What I'd build next

`docs/ROADMAP.md` has five items with concrete day-level sizings:

1. **Harden + evaluate the synthesis layer (~3 days)** — measure the RAG demonstrator with the same rigour as the retrieval layer. Hallucination rate, prompt ablation, cost regression, failure-state coverage.
2. **Query-type classifier (~1 day)** — route statutory questions to semantic-heavier weights, symptom-driven to hybrid, rights-refusal to semantic-only. The BM25 finding above directly informs this.
3. **Per-LA topic normalisation (~2 days)** — solve the 152-councils-152-formats problem by tagging topics from a shared taxonomy at ingest time.
4. **Reranker quantisation + domain adaptation (~2 days)** — make the reranker actually help instead of hurt.
5. **Parent-feedback loop (~1 day)** — close the eval-to-deployment loop.

---

## 9. Why this matters beyond SEN

Everything above is domain-specific, but the engineering discipline isn't. Any AI system that retrieves, ranks, or recommends faces the same choices: which fusion approach, what chunking strategy, how to score the thing, when to say "I don't know" instead of guessing.

The systems that get shipped without honest measurement are the ones that make the news for the wrong reasons. This project is a small example of the alternative — measure honestly, name what doesn't work, let the data update your priors, reproduce every claim from the raw data.

That discipline is the part no AI tool can one-shot for you. It's where the engineering is.
