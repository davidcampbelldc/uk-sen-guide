---
title: "Interview Preparation Reference for a SEN/SEND RAG Retrieval Project"
date: 2026-05-11
status: PARTIAL
question: "How does the SEN guidance RAG system work — from document ingestion and hybrid search through to evaluation — and what was learned at each stage?"
topic: docs
backfilled: 2026-10-05
---

# Interview Prep — Deep Technical Reference

A comprehensive guide to every concept, decision, and finding in this project. Written to prepare you to discuss each topic fluently at interview depth — from first principles through to the specific choices made here and what was learned.

This document goes deeper than the GLOSSARY (which defines terms) and CONCEPTS (which explains decisions in plain English). Here, each concept is unpacked fully: what it is, how it works, why it matters, and what this project learned about it.

---

## Table of Contents

1. [The Problem Domain](#1-the-problem-domain)
2. [RAG — Retrieval-Augmented Generation](#2-rag--retrieval-augmented-generation)
3. [Document Ingestion and Parsing](#3-document-ingestion-and-parsing)
4. [Chunking — Why and How](#4-chunking--why-and-how)
5. [BM25 — Keyword Search From First Principles](#5-bm25--keyword-search-from-first-principles)
6. [Embeddings and Semantic Search](#6-embeddings-and-semantic-search)
7. [Vector Databases and HNSW](#7-vector-databases-and-hnsw)
8. [Hybrid Search and Score Fusion](#8-hybrid-search-and-score-fusion)
9. [Cross-Encoder Reranking](#9-cross-encoder-reranking)
10. [Evaluation Methodology](#10-evaluation-methodology)
11. [Key Findings and What They Mean](#11-key-findings-and-what-they-mean)
12. [System Design Decisions](#12-system-design-decisions)
13. [The Synthesis Layer (RAG Demonstrator)](#13-the-synthesis-layer-rag-demonstrator)
14. [Performance and Operational Concerns](#14-performance-and-operational-concerns)
15. [What I'd Do Differently / Next](#15-what-id-do-differently--next)
16. [Likely Interview Questions and Talking Points](#16-likely-interview-questions-and-talking-points)

---

## 1. The Problem Domain

### What is SEN/SEND?

Special Educational Needs (SEN) — or SEND when including Disabilities — is the UK legal framework for supporting children who need additional help in education. The framework is governed by the Children and Families Act 2014 and operationalised through the SEND Code of Practice, a 292-page statutory guidance document.

### Why is this a hard information-retrieval problem?

Three properties make SEN guidance unusually challenging to search:

**Fragmentation.** England has 152 local authorities (councils), each of which must publish a "Local Offer" describing available SEN support in its area. But there is no common schema, no shared format, and no central index. The same statutory duty ("the council must...") is described 152 different ways. Any serious SEN tool has to deal with this fragmentation as a first-class problem.

**Adversarial context.** SEND Tribunal statistics show that ~95% of appeals find in favour of families. That figure tells you something important: parents are frequently given incorrect refusals by local authorities. The information environment is not neutral — parents need accurate retrieval of their legal rights, not just "related content".

**Mixed document types.** The material parents need spans PDFs (the Code of Practice), HTML pages (gov.uk, council websites, charity advice), and spreadsheets (DfE statistics). A retrieval system that only handles one format misses the picture.

### Why this matters for the system design

These properties drove specific choices:
- **Section-reference preservation** (§9.14 must survive chunking) because statutory citations are how parents and tribunals reference obligations
- **Open-schema metadata** so LA-specific fields (council name, region, doc_type) can coexist with charity-specific fields without schema migration
- **Precision-biased source filtering** because off-topic results are actively harmful in an adversarial context — returning a "Section 19" from the wrong Act could mislead a parent

---

## 2. RAG — Retrieval-Augmented Generation

### The core idea

A language model (like Claude or GPT) generates text. But it generates from its training data and can hallucinate — confidently state things that are wrong. RAG addresses this by:

1. **Retrieving** relevant passages from a trusted corpus first
2. **Augmenting** the language model's input with those passages as context
3. **Generating** an answer grounded in the retrieved evidence

The model's job shifts from "know the answer" to "synthesise an answer from the evidence I've been given". This makes outputs citable and auditable.

### Why retrieval is the load-bearing layer

If retrieval returns the wrong passages, the generation step synthesises a confident answer from irrelevant context — worse than no answer at all. The quality ceiling of any RAG system is set by its retrieval layer. This is why this project focuses evaluation on retrieval quality (P@5, R@5, NDCG@5) rather than generation quality — get retrieval right first.

### How this project implements RAG

The retrieval layer is the graded submission: four search configurations, 43 evaluated queries, reproducible metrics. The generation layer (the "synthesis layer") is shipped as a demonstrator but explicitly not evaluated to the same standard. This was a deliberate scoping decision — measuring retrieval rigorously in the time available was more honest than spreading evaluation thinly across both layers.

---

## 3. Document Ingestion and Parsing

### What "ingest" means

Ingestion is the process of getting documents from their original sources into a uniform internal representation that the rest of the system can work with. Each source type needs its own adapter because the formats differ fundamentally.

### Source-specific adapters

| Source | Format | Parsing challenge | Approach |
|---|---|---|---|
| SEND Code of Practice | PDF (292 pages) | Numbered section headings (§9.14) must be detected and preserved | `pypdf` + `pdfplumber` with heading-detection regex; sections become metadata |
| gov.uk SEND pages | HTML | Navigation chrome, sidebars, footers pollute the text | `beautifulsoup4` extracts main content block only |
| DfE statistics | XLSX workbooks | Each sheet has a different schema; multi-row headers | `openpyxl` reads each sheet; heuristic header-row detection; each sheet becomes one Document with title + schema + sample rows |
| Local Authority Local Offers | HTML (15 councils) | 15 councils, 15 different site structures | Generic HTML extraction with council-specific URL patterns |
| IPSEA + Contact | HTML | Charity advice articles with varying structure | `beautifulsoup4` with content-block heuristics |

### Key design choices

**Caching.** Every fetched document is cached to disk by URL hash. Re-running ingest skips the network request if the cache is valid. This matters for reproducibility — the exact same corpus can be rebuilt without depending on external servers being available.

**Deterministic parsing.** No LLM is used in the parsing pipeline. PDFs are parsed with traditional tools, not "AI-powered" document understanding. This keeps the pipeline deterministic: same input always produces same output. Important for reproducibility and for debugging — if a chunk is wrong, you can trace the cause through deterministic code.

**One-document-per-sheet for spreadsheets.** DfE statistics come as Excel workbooks where each sheet is a different statistical table (SEN by age group, SEN by region, etc.). Each *row* is thin ("Westminster, Year 10, 2023, 157 children") — not useful as a standalone search result. Each *sheet* is the meaningful retrieval unit: it has a title, a schema, and context about what the numbers represent. So each sheet becomes one Document with a text description including the title, column names, row count, and sample rows.

### Stable identifiers

Every document gets a stable ID: `<source>::<hash(source_id)>`. Every chunk gets: `<doc_id>::<seq>[::<section_ref>]`. These IDs are deterministic — derived from content, not from insertion order. Rerunning the pipeline on the same content produces the same IDs. This is critical for evaluation (ground-truth matchers reference metadata, not fragile IDs) and for incremental updates (the system can detect "this chunk hasn't changed" without re-processing).

---

## 4. Chunking — Why and How

### Why chunk at all?

Search engines retrieve passages, not entire documents. An 800-page PDF returned as a search result is useless — the user needs to know *which part* is relevant. Chunking breaks documents into smaller, self-contained passages that can be individually retrieved, scored, and cited.

But chunking involves trade-offs:
- **Too small**: chunks lose context; "the council must" without knowing which duty is meaningless
- **Too large**: chunks are diluted; a chunk containing 20 paragraphs will match many queries weakly rather than any query strongly
- **Structure-blind splitting**: cuts mid-sentence, mid-paragraph, or mid-section, destroying the citation anchors that make statutory content usable

### Two strategies implemented

**FixedSizeChunker** (baseline). Splits every N characters (default: 2,000) with an overlap window (default: 200 characters). Simple, predictable, structure-blind. The overlap ensures a sentence that falls on a boundary appears in both chunks, so it isn't lost. But it has no concept of document structure — it will happily split "§9.14 The local authority must..." from its continuation "...secure the special educational provision specified in the EHC plan."

**HeadingBoundaryChunker** (default). Detects section headings using regex patterns (numbered headings like "9.14", "Chapter 6", heading-level HTML tags). Splits at heading boundaries so each chunk corresponds to a natural section of the document. If a section exceeds the maximum chunk size, it falls back to fixed-size splitting within that section. Sections smaller than the minimum are merged with their successor.

### Why heading-boundary is the default

The critical metric: **91% of chunks preserve their section reference** with the heading-boundary chunker, vs. 0% with fixed-size. For statutory content — where a parent needs to cite "paragraph 9.14 of the SEND Code of Practice" to a tribunal — section-reference preservation is the job. A retrieval result that says "this is from the SEND Code of Practice somewhere" is much less useful than one that says "this is §9.14".

### Token approximation

This project approximates token counts using `len(text) / 4` (the "chars/4 rule") rather than running the actual tokeniser for each chunk. This is standard practice — the exact token count matters for language model context windows, but for chunking purposes an approximation within 10-15% is sufficient and avoids a dependency on a specific tokeniser.

### Content-hashed chunk filenames

A chunker's configuration (strategy, max_size, overlap) is hashed into a 16-character hex string. The output JSONL file includes this hash in its filename: `chunks-<hash>.jsonl`. This means different chunker configurations produce different files and can be compared side-by-side without overwriting each other. It also means the system knows whether it needs to re-chunk — if the config hash matches an existing file, the chunks are already up to date.

---

## 5. BM25 — Keyword Search From First Principles

### What problem does keyword search solve?

Given a query like "EHCP appeal deadline", find documents that contain those specific words. This sounds simple, but doing it well requires answering: *which* documents, and in what *order*?

### Term Frequency (TF)

The simplest idea: a document mentioning "EHCP" five times is probably more about EHCPs than one mentioning it once. Term Frequency counts how often each query word appears in a document.

But raw term frequency has a problem: a document mentioning "EHCP" 100 times isn't 100x more relevant than one mentioning it 10 times. The relationship saturates — the first few mentions tell you the document is relevant; additional mentions add diminishing information.

### Inverse Document Frequency (IDF)

Not all words are equally informative. "The" appears in every document — matching on "the" tells you nothing. "EHCP" appears in relatively few documents — matching on "EHCP" is highly informative.

IDF captures this: `IDF(term) = log(N / df(term))` where N is the total number of documents and df(term) is how many documents contain the term. Rare terms get high IDF (informative); common terms get low IDF (uninformative).

### TF-IDF (the predecessor)

Multiply them: `TF-IDF(term, doc) = TF(term, doc) * IDF(term)`. A document scores highly when it contains rare, query-relevant terms frequently. This was the dominant search algorithm for decades.

### BM25 — the improvement over TF-IDF

BM25 (Best Match 25, published by Robertson et al. in the 1990s) refines TF-IDF with two key improvements:

1. **Saturation function for term frequency.** Instead of raw TF, BM25 uses: `TF * (k1 + 1) / (TF + k1 * (1 - b + b * dl/avgdl))`. The k1 parameter controls how quickly term frequency saturates (default ~1.5). After a few mentions, additional occurrences add very little to the score. This prevents long documents from dominating just because they mention everything.

2. **Document length normalisation.** The `b` parameter (default ~0.75) controls how much shorter documents are boosted relative to longer ones. The intuition: if a 100-word document mentions "EHCP" three times, that's more concentrated than a 10,000-word document mentioning it three times. The `dl/avgdl` term (document length divided by average document length) captures this.

### Why BM25 is still relevant in 2026

Despite being 30+ years old, BM25 remains standard because:
- It's fast (in-memory, no model inference)
- It's interpretable (score = word overlap, weighted by rarity)
- It catches exact phrase matches that semantic search can miss
- It has zero cost per query (no API, no GPU)
- It's a strong baseline — any system that can't beat BM25 should be questioned

### BM25 in this project

Uses the `bm25s` library (pure Python, ~100x faster than the more common `rank-bm25`). The index is built over all 8,691 chunks with an English stemmer (reducing "appealing" and "appeals" to the same root form). Stored as a binary file + a JSON chunk manifest for off-disk persistence.

### What BM25 cannot do

BM25 is purely lexical — it matches words, not meaning. "How do I challenge a local authority refusal?" won't match a passage about "appealing an LA decision" unless those exact words overlap. This is the gap that semantic search fills.

---

## 6. Embeddings and Semantic Search

### The conceptual leap from keywords to meaning

Keyword search asks: "do these texts share words?" Semantic search asks: "do these texts share meaning?" To answer the second question, you need a way to represent meaning numerically — that's what embeddings are.

### What is an embedding?

An embedding is a list of numbers (a "vector") that represents the meaning of a piece of text. In this project, each embedding has 1,024 numbers. You can think of it as a coordinate in a 1,024-dimensional space — texts with similar meanings end up near each other in this space, even if they use different words.

For example, "EHCP appeal" and "challenging an Education Health and Care Plan decision" would produce embeddings that are close together geometrically, even though they share almost no words.

### How are embeddings produced?

A neural network — specifically, a transformer model — reads the text and outputs the embedding vector. The model has been trained on massive amounts of text to learn that similar meanings should produce similar vectors. The training process (called "contrastive learning" for retrieval models) shows the model pairs of texts that are related and pairs that aren't, and adjusts the model's weights until it reliably places related texts near each other in vector space.

### BGE-large — the specific model used here

`BAAI/bge-large-en-v1.5` (from the Beijing Academy of AI) is the embedding model this project uses. Key properties:

- **1,024-dimensional output** — each text becomes a list of 1,024 numbers
- **Open weights** — freely downloadable, no API key needed
- **CPU-runnable** — doesn't require a GPU, though it's faster with one
- **Strong benchmark performance** — competitive on BEIR (the standard retrieval benchmark suite) with paid alternatives like OpenAI's `text-embedding-3-large`
- **English-focused** — trained primarily on English text, which suits a UK-specific corpus

Why not use OpenAI or Cohere's embedding APIs? Two reasons: (1) a reviewer can't reproduce results without an API key, and (2) per-query cost is zero with a local model, making cost claims honest.

### Cosine similarity — how "nearness" is measured

Once you have two embedding vectors, you need to measure how similar they are. This project uses cosine similarity, which measures the angle between two vectors:

`cosine_similarity(A, B) = (A . B) / (|A| * |B|)`

Where `A . B` is the dot product (multiply corresponding elements and sum) and `|A|` is the magnitude (square root of sum of squares).

Intuitively: two vectors pointing in the same direction have cosine similarity close to 1 (very similar). Two vectors pointing in perpendicular directions have cosine similarity close to 0 (unrelated). Two vectors pointing in opposite directions have cosine similarity close to -1 (opposite meaning).

Why cosine rather than Euclidean distance? Cosine similarity is invariant to vector magnitude — it only cares about direction. This matters because embedding models don't guarantee that all vectors have the same length, so two texts about the same topic could have different magnitudes but point in the same direction. Cosine similarity sees them as similar; Euclidean distance might not.

### Bi-encoder architecture

The embedding approach used here is called a "bi-encoder" because the query and the documents are encoded independently:

1. At index time: encode each chunk independently, store the vector
2. At query time: encode the query independently, find the nearest stored vectors

This is fast because step 1 is done once (offline), and step 2 only requires encoding one short query plus a nearest-neighbour lookup. But it's limited because the query and document never "see" each other during encoding — the model can't attend to the specific relationship between them. This limitation is what cross-encoders (Section 9) address.

### What "semantic" actually means in practice

"Semantic search" sounds magical, but it has specific failure modes:
- **Homonyms**: "bank" (financial institution vs. river bank) — the model has to guess from context
- **Extremely domain-specific terminology**: if the training data didn't include SEN law, the model may map legal terms inaccurately
- **Exact references**: "§9.14" is a symbol, not a concept — semantic search may not find it unless the model learned that "9.14" relates to specific statutory content (surprisingly, BGE-large *does* handle this — see Section 11)

---

## 7. Vector Databases and HNSW

### Why you need a vector database

You have 8,691 chunks, each represented as a 1,024-dimensional vector. Given a query vector, you need to find the most similar chunk vectors. The brute-force approach — compute cosine similarity against all 8,691 vectors — works at this scale (~10ms), but doesn't scale to millions. Vector databases solve the scaling problem.

### Qdrant — the vector DB used here

Qdrant is an open-source vector database that:
- Stores vectors + arbitrary metadata (the "payload")
- Runs nearest-neighbour search efficiently via HNSW indexing
- Supports metadata filtering (e.g., "only search chunks from gov.uk sources")
- Runs locally in Docker — no cloud account needed

Alternatives considered and rejected: Pinecone (cloud-only, needs API key), Chroma (weaker metadata filtering), pgvector (requires Postgres setup), DuckDB+VSS (immature for hybrid search). The driving constraint was reviewer reproducibility — "docker compose up" is all a reviewer needs.

### HNSW — How Qdrant finds nearest neighbours fast

HNSW (Hierarchical Navigable Small World) is the algorithm Qdrant uses to find approximate nearest neighbours without comparing against every vector.

**The intuition.** Imagine a network of cities connected by roads. To get from London to a small village in Scotland, you wouldn't check every village in the UK. You'd take a motorway (long-distance connection) to Edinburgh, then a regional road to the right county, then a local road to the village. HNSW works similarly but in vector space.

**The layers.** HNSW builds a multi-layer graph over the vectors:
- **Top layer**: few nodes, long-distance connections (the "motorways")
- **Middle layers**: more nodes, medium-distance connections
- **Bottom layer**: all nodes, short-distance connections (the "local roads")

To find the nearest neighbour of a query vector, the search starts at the top layer, greedily follows connections toward the query, then drops down to a finer layer and repeats. Each layer refines the search.

**Approximate, not exact.** HNSW doesn't guarantee finding the absolute nearest neighbour — it finds a very good approximation in O(log n) time instead of O(n). The `ef` parameter controls the accuracy/speed trade-off: higher ef = more neighbours explored at each step = more accurate but slower. For retrieval purposes, approximate is fine — the difference between rank 1 and rank 2 is usually negligible.

**Why this matters for the project.** At 8,691 chunks, brute-force search is fast enough (~10ms). HNSW is overkill at this scale. But the architecture is correct for production — if the corpus grew to 1M+ chunks, HNSW would maintain sub-100ms search while brute-force would become seconds.

### Metadata filtering in Qdrant

Every chunk carries open-schema metadata: source, section_ref, local_authority, charity, publication_year, etc. Qdrant indexes these metadata fields alongside the vectors, enabling filtered search: "find the 5 most semantically similar chunks *where source = 'gov.uk/send-cop'*".

This is done as a pre-filter (filter first, then search the filtered subset) rather than a post-filter (search everything, then filter). Pre-filtering is important when the filter is selective — if only 5% of chunks are from gov.uk, post-filtering would waste 95% of the search effort.

---

## 8. Hybrid Search and Score Fusion

### Why combine keyword and semantic search?

Each search method has complementary strengths:

| Situation | BM25 (keyword) | Semantic |
|---|---|---|
| Query uses exact terms from the document | Strong | May miss |
| Query is a paraphrase of the document content | Weak | Strong |
| Query contains a rare technical term | Strong (IDF boost) | Depends on training data |
| Query is conceptual ("support for anxious children") | Weak | Strong |
| Query contains a section reference (§9.14) | Expected strong, actually weak (see findings) | Unexpectedly strong |

Hybrid search runs both retrievers and combines their results. The hypothesis: the union of keyword matches and meaning matches should outperform either alone. **This hypothesis was confirmed** — hybrid beat semantic on 4 of 7 query types and matched it on 2 more.

### The score combination problem

BM25 scores and cosine similarity scores are on completely different scales:
- BM25 scores: typically 5-50 (unbounded, depends on term rarity and document length)
- Cosine similarity: 0 to 1 (bounded)

You can't just add them — a BM25 score of 30 would dominate a cosine similarity of 0.8. The scores need to be normalised to a common scale before combining.

### Weighted normalised-sum fusion (the default)

This project uses min-max normalisation:

`normalised_score = (score - min_score) / (max_score - min_score)`

This maps each retriever's scores to the range [0, 1], regardless of the original scale. Then:

`fused_score = w_bm25 * normalised_bm25 + w_semantic * normalised_semantic`

With default weights: w_bm25 = 0.35, w_semantic = 0.65. The weights are tunable. They were set empirically (semantic contributes more on this corpus, so it gets a higher weight).

**Why min-max rather than z-score normalisation?** Min-max is bounded [0, 1] and interpretable — a score of 0.8 means "80% of the way from worst to best candidate". Z-score normalisation (subtract mean, divide by standard deviation) is unbounded and less interpretable for this use case.

### Reciprocal Rank Fusion (RRF) — the alternative

RRF ignores scores entirely and uses only ranks:

`RRF_score = sum over retrievers of: 1 / (k + rank)`

Where k is a constant (typically 60). A passage ranked #1 by BM25 and #3 by semantic gets: `1/(60+1) + 1/(60+3) = 0.0164 + 0.0159 = 0.0323`.

**Advantages over weighted normalised-sum:**
- Parameter-free (no weight tuning needed)
- Robust to score-distribution differences between retrievers
- Doesn't require normalisation

**Disadvantages:**
- Throws away score information (a passage ranked #1 with score 0.99 is treated the same as one ranked #1 with score 0.51)
- No way to express "trust semantic 2x more than BM25" — all retrievers contribute equally

This project exposes RRF as a fallback fusion mode.

### Why the score breakdown is returned to callers

Every search result includes: `{bm25: 0.42, semantic: 0.78, reranker: null, fused: 0.67}`. This transparency has two purposes:
1. **Debugging**: if a result seems wrong, you can see which retriever contributed it and why
2. **Downstream confidence**: the synthesis layer can distinguish "both retrievers agree this is top-1" from "only BM25 thinks this is relevant" and weight its confidence accordingly

---

## 9. Cross-Encoder Reranking

### The architectural difference: bi-encoder vs. cross-encoder

**Bi-encoder** (used for initial retrieval): query and document are encoded *independently*. The model never sees them together. Fast (encode once, compare many), but can't model the specific interaction between query and document.

**Cross-encoder** (used for reranking): query and document are encoded *together* as a single input. The model reads `[query] [SEP] [document]` and outputs a single relevance score. Slower (must run the full model for every query-document pair), but more accurate because it can attend to the specific relationship.

Analogy: A bi-encoder is like matching CVs to job descriptions by comparing their keyword summaries. A cross-encoder is like a recruiter reading each CV alongside the specific job description and judging the fit.

### Why rerank rather than use cross-encoders for everything?

Cross-encoders are too slow for initial retrieval. Scoring 8,691 chunks with a cross-encoder would take ~30 seconds per query. Instead, the standard approach is:
1. Use fast retrieval (BM25 + bi-encoder) to get a candidate set (top 50)
2. Use the slow-but-accurate cross-encoder to re-score only those 50
3. Return the reranked top 5

This is called a "telescoping" or "multi-stage" retrieval pipeline. Each stage is more accurate but more expensive, applied to a progressively smaller candidate set.

### The reranker model: BGE-reranker-base

`BAAI/bge-reranker-base` (~278 million parameters). Properties:
- Cross-encoder architecture (reads query + passage together)
- CPU-runnable (important: no GPU required)
- Lazy-loaded (only loaded into memory on first use, keeping startup fast)
- ~300ms to score 50 candidates on CPU

### The surprising finding: reranking hurt quality

On this corpus, `hybrid_rerank` scored *lower* than `hybrid` on every metric:
- NDCG@5: 0.238 vs. 0.285 (a drop of 0.047)
- P@5: 0.260 vs. 0.307

This contradicts the standard expectation that reranking improves quality. Possible explanations:

1. **Domain mismatch.** `bge-reranker-base` was trained on general web text, not statutory/legal language. Its relevance model may systematically prefer "web-like" passages over statutory ones, pushing the most legally precise passages down the ranking.

2. **Score distribution disruption.** The fused ordering from BM25 + semantic already encodes two complementary relevance signals. The cross-encoder produces a third signal trained on different data. If that third signal disagrees with both the first two on domain-specific queries, the reranked order is worse.

3. **Top-50 candidate pool may already be clean enough.** At 8,691 chunks, the top-50 from hybrid search likely contains most relevant passages. The reranker's theoretical advantage (accurately distinguishing "good" from "great" within the candidate pool) may be outweighed by its domain mismatch.

### What this means practically

- The `hybrid` config (no reranker) is both faster and better on this corpus
- The reranker adds 2+ seconds of latency for negative quality impact
- The fix is domain adaptation: fine-tune a reranker on SEN-specific query-passage pairs, or use a newer model (`bge-reranker-v2-m3`) that may generalise better

### Why reporting this honestly matters

In an assessment context, the temptation is to either (a) hide the reranker results or (b) not implement reranking at all. Reporting the negative result openly demonstrates:
- You measured rather than assumed
- You understand that "more model layers = better" isn't automatic
- You can diagnose why a component failed and propose remediation
- You don't cherry-pick results to fit a narrative

---

## 10. Evaluation Methodology

### Why evaluation matters more than architecture

You can build the most sophisticated retrieval pipeline in the world, but without rigorous evaluation you don't know if it works. Evaluation is the bridge between "I built a thing" and "the thing works, and here's proof".

### The three metrics: P@5, R@5, NDCG@5

All three are computed at k=5 (the top 5 results), which matches the user-facing experience — a parent will look at 5 results, not 100.

**Precision@5 (P@5)** — "Of the 5 results I showed the user, how many were actually relevant?"

`P@5 = (number of relevant results in top 5) / 5`

If 2 of 5 results are relevant, P@5 = 0.40. Measures noise — higher precision means fewer wasted results.

**Recall@5 (R@5)** — "Of all the relevant passages in the entire corpus, how many did I find in the top 5?"

`R@5 = (number of relevant results in top 5) / (total relevant in corpus)`

With thousands of potentially relevant chunks per query (because matcher-based ground truth matches on metadata like source + section prefix, which can hit many chunks), R@5 is always small. The *ratio* between configurations matters more than the absolute value.

**NDCG@5 (Normalised Discounted Cumulative Gain at 5)** — the most informative single metric.

NDCG answers: "Are the relevant results near the top?" It's position-aware: a relevant result at rank 1 is worth more than one at rank 5.

The formula, unpacked:

1. **Gain function**: `gain(relevance) = 2^relevance - 1`. A relevance grade of 2 gives gain = 3; grade 1 gives gain = 1; grade 0 gives gain = 0. The exponential means highly relevant results are worth disproportionately more.

2. **Position discount**: `discount(rank) = log2(rank + 1)`. Rank 1 discount = log2(2) = 1. Rank 5 discount = log2(6) = 2.585. Results further down the ranking are discounted more.

3. **DCG (Discounted Cumulative Gain)**: `DCG@5 = sum over positions 1-5 of: gain / discount`. Adds up the discounted gains.

4. **Ideal DCG**: sort all relevant passages by relevance, take the top 5, compute DCG. This is the best possible DCG@5.

5. **NDCG@5 = DCG@5 / Ideal_DCG@5**. Normalised to [0, 1]. 1.0 means the ranking is perfect; 0.0 means no relevant results appeared.

### Why NDCG is better than precision alone

Precision treats all positions equally — a relevant result at rank 5 counts the same as one at rank 1. But users look at rank 1 first. NDCG captures this: if both System A and System B have P@5 = 0.4 (2 relevant results in top 5), but System A puts them at ranks 1 and 2 while System B puts them at ranks 4 and 5, NDCG will score System A higher.

### Matcher-based ground truth (qrels)

Traditional evaluation requires a list of "correct answers" for each query — specific documents or passages judged as relevant. This is fragile: if you change the chunker, the chunk IDs change, and all your ground-truth labels break.

This project uses matcher-based ground truth instead. Each query has matchers like:

```yaml
matchers:
  - source: gov.uk/send-cop
    section_ref_prefix: "9."
    relevance: 2
  - charity: ipsea
    text_contains: ["appeal", "tribunal"]
    relevance: 1
```

At eval time, the harness scans the corpus: any chunk matching `source = gov.uk/send-cop AND section_ref starts with "9."` is marked as relevant at grade 2. This approach:
- **Survives chunker changes** — if you re-chunk with different settings, the matchers still select the right passages (because they match on metadata, not chunk IDs)
- **Is transparent** — you can read the matchers and understand *what* the query is supposed to find
- **Supports graded relevance** — a passage from the exact statutory section (grade 2) is worth more than one from a charity overview (grade 1)

### Why implement metrics directly rather than using a library?

Libraries like `ranx` implement standard metrics. But wrapping them adds a layer of indirection between your code and your claims. When you say "NDCG@5 = 0.285", a reviewer might ask: "what exactly does your NDCG implementation measure?" With direct implementation in `src/uk_sen_guide/eval/metrics.py`, the answer is "read the code — it's 30 lines". There's exactly one source of truth.

### Reproducibility

The raw per-query outputs are committed to `eval_runs/` as JSONL files. A 15-line Python script recomputes every aggregate in the REPORT from these files. This means a reviewer doesn't have to trust the numbers — they can verify them independently. Reproducibility isn't just good practice; it's the difference between "I claim these results" and "here are the results, check my work."

---

## 11. Key Findings and What They Mean

### Finding 1: Hybrid beats everything (but not by much)

| Config | NDCG@5 |
|---|---|
| BM25 | 0.221 |
| Semantic | 0.267 |
| **Hybrid** | **0.285** |
| Hybrid + rerank | 0.238 |

Hybrid gains +0.018 NDCG over semantic alone. That's modest but consistent across query types. The interpretation: BM25 adds marginal signal on top of semantic search. It rarely dominates, but it rescues some queries where semantic search misses exact terminology.

**Interview angle:** "Hybrid search worked, but the gain was modest. The real value of BM25 wasn't as a standalone retriever — it was as a safety net for the cases semantic search gets wrong."

### Finding 2: BM25 never beats semantic standalone (the prior update)

Going in, the hypothesis was: "BM25 will dominate statutory-citation queries because parents searching for '§9.14' need lexical matching."

The data said the opposite. On statutory-citation queries:
- BM25 NDCG: 0.072
- Semantic NDCG: 0.163 (2.3x better)

Why? The BGE-large embedding model has absorbed enough legal/statutory English during training that "duties under Section 19 of the Children and Families Act 2014" is recognised as *about local authority SEN duties* even when the target passage uses different phrasing. Meanwhile, BM25 happily matches "Section 19" against a DfE publication about Section 19 of *a completely different Act* — pure keyword matching has no concept of which Act you mean.

**Interview angle:** "This was the finding that most updated my priors. I had allocated engineering time for a BM25-heavy query router for statutory queries. The data inverted that plan. This kind of prior-update only happens if you isolate each component and measure it head-to-head."

### Finding 3: The metric-vs-usefulness gap

The 8 real-parent-scenario queries scored NDCG@5 = 0.238 (24%). But manual inspection showed 6 of 8 had at least one directly useful result in the top 3 — 75% human-judged usefulness.

Why the gap? Matcher-based ground truth is conservative. It marks passages as relevant when they match specific metadata patterns (source + section reference + keyword anchors). But retrieval finds passages that are *substantively useful* without satisfying those exact matchers. Example: a query about "evidence for a mental-health-concerns appeal" matches §9.14 of the Code of Practice (the formal legal test), which is in the ground truth. But it also returns IPSEA articles about mental health sections of EHC plans (sections C/D/G/H), which aren't in the ground truth but are directly useful.

**Interview angle:** "The metric undercounts. That's not a bug — it's a known property of any discrete ground-truth evaluation. Naming the gap explicitly and having a plan to close it (LLM-as-judge evaluation) is the mature response."

### Finding 4: Reranking hurts quality on this domain

Covered in Section 9. The key interview point: "I shipped a component that made things worse, measured it honestly, and reported the finding. The temptation to either hide the result or not implement reranking at all would have been dishonest."

### Finding 5: The LA fragmentation problem is real and measurable

Of 16 Local Authorities probed:
- 6 returned 403/404 (not accessible)
- Of the 10 accessible, document yield ranged from 3 (Leicester, Hackney) to 80 (Lewisham, Brighton, Oxfordshire at the cap)
- Site structures vary completely — some use sitemaps, some don't, URL patterns differ, content depth differs

This isn't a theoretical problem — it's a concrete measurement. Any production SEN tool will need LA-specific adapters or a shared taxonomy.

---

## 12. System Design Decisions

### "No framework" — why build everything explicitly?

Frameworks like LlamaIndex and Haystack provide pre-built RAG pipelines. They're faster to build with but hide decisions. In an assessment context, "defending the retrieval decisions" is exactly the work. Building BM25 + dense + rerank + fusion explicitly means:
- Every design choice is visible in code, not buried in framework defaults
- Trade-offs are yours to justify, not the framework's
- A reviewer can read the fusion logic (50 lines of Python) rather than tracing through framework abstractions

**Trade-off acknowledged:** this approach is slower to build and doesn't benefit from framework-level optimisations. At production scale with a team, using a framework would be the right call. For a take-home assessment, explicit is honest.

### File-based storage — why no database for chunks?

The chunks are stored as JSONL files, not in SQLite, Postgres, or MongoDB. At ~8.7K chunks, this is a deliberate choice:
- Qdrant already stores vectors + metadata — it *is* the metadata database
- BM25 needs full chunk text in process memory anyway (the library design requires it)
- No concurrent writers during ingest — single-writer semantics are free with files
- Files are inspectable with `jq`, `grep`, and `cat` — no DB setup in the README

At 100K+ chunks or with concurrent writers, this would move to SQLite. The current approach is right for the current scale; documenting where it breaks is part of the engineering judgment.

### Open-schema metadata — why Dict[str, Any]?

Every chunk carries `metadata: Dict[str, Any]` that absorbs source-specific fields. A SEND Code of Practice chunk might have `{source: "gov.uk/send-cop", section_ref: "9.14", chapter: 9}`. An IPSEA article might have `{source: "charity-site", charity: "ipsea", topic: "appeals"}`. A DfE statistics sheet might have `{source: "dfe-tabular", publication_year: 2023, format: "xlsx"}`.

A fixed schema would require anticipating every possible field across all sources. Open-schema absorbs new sources without migration — you just add fields. The downside is less type safety; the upside is flexibility at the cost of validation at the boundaries.

### Stable identifiers via content hashing

`doc_id = <source>::<hash(source_id)>` and `chunk_id = <doc_id>::<seq>[::<section_ref>]`. These are deterministic — same content, same ID, every time. Benefits:
- Evaluation ground truth survives re-ingestion
- Incremental updates can detect "this chunk hasn't changed"
- No dependency on database auto-increment IDs

---

## 13. The Synthesis Layer (RAG Demonstrator)

### What it is

A confidence-gated, citation-bearing answer-generation layer. Takes the top retrieved passages, sends them to a language model as context, and produces a natural-language answer with inline citations.

### Confidence gating

If the top retrieved passage's fused score is below 0.30, the system skips the language model entirely and returns a pre-written escalation message pointing to IPSEA's helpline (0800 018 4016). This:
- Prevents hallucination on weak retrievals
- Saves cost (no LLM call)
- Surfaces the system's epistemic limit honestly — "I don't have a confident answer, here's where to get expert help"

### Five response states

| State | Meaning | Behaviour |
|---|---|---|
| `high` | Strong retrieval, confident synthesis | Full answer with citations + disclaimer |
| `medium` | Moderate retrieval | Answer with citations + stronger caveats |
| `low` | Weak retrieval, below threshold | Skip LLM, return IPSEA escalation |
| `llm_error` | LLM call failed | Return retrieved citations without synthesis (retrieval still worked) |
| `out_of_scope` | Query detected as non-SEN | Polite redirect, no retrieval attempted |

The `llm_error` state is a design detail worth noting: when the LLM fails, the *retrieval results are still valid*. The UI shows the source passages without a synthesised answer. Partial degradation is better than total failure.

### Dual-provider architecture

The synthesis layer supports two LLM providers:
- Anthropic Claude (Sonnet) — preferred
- z.ai GLM (OpenAI-compatible API) — alternative

Provider is selected at startup from environment variables. Switching providers requires no code change — just set different env vars. This was built pragmatically (z.ai is a free alternative for development) but demonstrates a useful pattern: abstracting the LLM provider behind a common interface.

### Per-call cost tracking

Every synthesis call logs: input tokens, output tokens, provider rate, and total cost in GBP. This enables cost monitoring and eventual cost regression testing (not yet implemented — roadmap item #1).

### Why it's "not evaluated"

The synthesis layer works but isn't measured to the same standard as retrieval. Missing evaluations:
- Hallucination rate (how often does the answer claim something not in the retrieved passages?)
- Prompt ablation (which parts of the system prompt earn their place?)
- Cost regression (does a prompt change double the cost?)
- Failure-state coverage (does every error path actually produce the right response state?)

Building all of this would take ~3 days (ROADMAP item #1). Shipping the demonstrator without pretending it's production-evaluated is more honest than either leaving it out or claiming it's ready.

---

## 14. Performance and Operational Concerns

### Latency budget

Target: p95 < 500ms (95% of queries complete within half a second).

| Stage | Budget | Actual |
|---|---|---|
| Query embed (BGE-large) | 30ms | ~30ms |
| BM25 retrieve top-100 | 20ms | <1ms |
| Dense retrieve top-100 (Qdrant HNSW) | 80ms | ~80ms |
| Fuse + deduplicate | 5ms | ~5ms |
| Rerank top-50 (cross-encoder) | 300ms | ~2,000ms |
| Metadata filter + response | 10ms | <10ms |
| **Total (with rerank)** | 445ms | **~2,300ms** |
| **Total (without rerank)** | ~145ms | **~100ms** |

The reranker blows the budget. Without reranking, `hybrid` sits at ~100ms p95 — well within budget. This is another practical argument against using the reranker in its current form.

### Cold vs. warm cache

First query after startup pays model-load latency:
- Semantic config cold: 3,823ms (embedding model loading)
- Hybrid_rerank cold: 6,671ms (embedding model + reranker loading)
- Warm subsequent queries: ~100ms for hybrid, ~2,000ms for hybrid_rerank

The cold-start penalty is a one-time cost. In production, you'd pre-warm models at startup (load them before accepting traffic).

### Concurrency

Under load test (20 concurrent requests, 20s run):
- 10 concurrent: 11.4 req/s, p50 = 884ms, p95 = 967ms, 0 errors
- 20 concurrent: 10.1 req/s, p50 = 1,917ms, p95 = 2,293ms, 0 errors

Latency degrades with concurrency because the embedding model is CPU-bound and Python's GIL (Global Interpreter Lock) serialises CPU-intensive work. Production path: run multiple uvicorn workers (`--workers N`), each with its own model instance, or use a GPU for embedding inference.

### Cost per 1,000 queries

All models are local and open — zero per-query API cost. The dominant cost is one-time corpus embedding (~72 CPU-minutes on the test hardware). Steady-state at AWS c5.large spot pricing:
- semantic/hybrid: ~£0.001 per 1,000 queries
- hybrid_rerank: ~£0.022 per 1,000 queries (cross-encoder inference dominates)

This is essentially free. The cost surface is compute, not API.

### Observability

- **Prometheus metrics** via `prometheus-fastapi-instrumentator`: HTTP request counts, latency histograms per config, reranker invocation counts, candidate pool sizes
- **Structured JSON logs** via `structlog`: every `/search` call emits one JSON line with `query_id`, `config`, `latency_ms`, candidate counts, returned count — suitable for ingestion into any log aggregation system

---

## 15. What I'd Do Differently / Next

### Immediate (ROADMAP items, sized in days)

1. **Harden synthesis layer (~3 days)** — hallucination eval, prompt ablation, cost regression, failure-state coverage. The demonstrator exists; the measurement rigour doesn't.

2. **Query-type classifier (~1 day)** — route different query types to different retrieval configs. The per-type evaluation data already tells us which config wins for which query type. A lightweight classifier (even a regex-based one) would route statutory queries to semantic-heavy weights, symptom-driven to hybrid, rights-refusal to semantic-only.

3. **Per-LA topic normalisation (~2 days)** — solve the "152 councils, 152 formats" problem by tagging topics from a shared taxonomy at ingest time. Then "what speech therapy is available" can search across all LAs by topic rather than relying on each council using the same terminology.

4. **Reranker improvement (~2 days)** — either fine-tune on SEN query-passage pairs (domain adaptation) or swap to a newer model (`bge-reranker-v2-m3`). Optionally quantise the model (reduce numerical precision from 32-bit to 8-bit) for faster inference with minimal quality loss.

5. **Parent-feedback loop (~1 day)** — log which retrieved results parents actually click on. Use click-through data as implicit relevance feedback to tune fusion weights and identify queries where the system consistently fails.

### Architectural changes at scale

- **Move chunks to SQLite or Postgres** when concurrent writers or 100K+ chunks justify it
- **GPU inference** for embedding at high throughput
- **Model distillation** — train a smaller, faster embedding model on the SEN domain specifically
- **Incremental re-embedding** — track which chunks changed at the content-hash level and only re-embed those

---

## 16. Likely Interview Questions and Talking Points

### "Walk me through the architecture"

Start with the four-stage pipeline: ingest, chunk, index (BM25 + dense), retrieve (four configs). Emphasise: each stage is independently testable; each retrieval config shares the same result shape so the eval harness treats them uniformly.

### "Why didn't you use LlamaIndex / Haystack?"

"The assessment asks me to defend retrieval decisions. Frameworks make those decisions for you. Building explicitly means every choice — fusion weights, chunking strategy, reranker placement — is mine to justify. At production scale with a team, I'd use a framework. For demonstrating engineering judgment, explicit is honest."

### "How does BM25 actually work?"

TF (how often the word appears), IDF (how rare it is globally), saturation (diminishing returns after a few mentions), length normalisation (short documents get a boost). It's fast, free, interpretable, and 30 years old for a reason.

### "What's the difference between a bi-encoder and a cross-encoder?"

"Bi-encoder: query and document encoded separately, then compared. Fast (encode once, compare many). Cross-encoder: query and document read together. Slow (must run for every pair) but more accurate. We use bi-encoder for initial retrieval (fast over 8,691 chunks) and cross-encoder only for reranking the top 50."

### "Why did the reranker make things worse?"

"Likely domain mismatch — bge-reranker-base was trained on general web text, not statutory/legal language. Its relevance model may systematically prefer web-like passages over the most legally precise ones. The fix is domain adaptation or a newer model. The important thing: I measured it and reported the finding honestly rather than assuming more layers = better."

### "What's NDCG and why use it?"

"It rewards relevant results near the top. Precision says 'how many of 5 are relevant'; NDCG says 'are the relevant ones at rank 1-2 or rank 4-5?' It uses a log discount so rank 1 is worth much more than rank 5. The '5' means we only look at the top 5 results — matching what a user actually sees."

### "How would you improve the system?"

Lead with the query-type classifier (low cost, data already exists to inform it), then reranker domain adaptation, then LLM-as-judge evaluation to close the metric-vs-usefulness gap.

### "What are you most proud of?"

"The metric-vs-usefulness gap finding on the parent-scenario queries. NDCG said 24%; human inspection said 75%. Most reports would show only the headline number. Naming the gap and understanding *why* it exists (conservative matcher-based ground truth) is the kind of insight that only comes from reading the actual results rather than trusting the metrics blindly."

### "What would you do with more time?"

See Section 15 above. Lead with the synthesis layer evaluation — it's the biggest gap between "demonstrator" and "production-ready", and it's concretely sized at ~3 days.

### "Tell me about a decision you changed your mind on"

"I was going to route statutory-citation queries to BM25-heavy weights. The per-type evaluation showed semantic beats BM25 2.3:1 on those queries. BGE-large has absorbed enough legal English that 'duties under Section 19' is recognised semantically, while BM25 matches the wrong Act. I inverted the plan. That prior-update only happened because I isolated BM25 as its own first-class config and measured it head-to-head."

### "How did you handle the SEN domain specifically?"

Three domain-specific choices: (1) heading-boundary chunking that preserves §9.14 citation anchors (91% preservation rate), (2) precision-biased source filtering because off-topic results in an adversarial context are actively harmful, (3) confidence gating that escalates to IPSEA's helpline rather than hallucinating answers to vulnerable parents.

### "What's the weakest part of the system?"

"30% Precision@5 means 3-4 of every 5 results are off-target. For a tool going to stressed parents navigating a legal process, that's not acceptable without an additional trust layer. The confidence gate helps, but the fundamental retrieval precision needs improvement before this is production-ready."
