# Glossary

Plain-English definitions of the terms, acronyms, and model names used across the repo and its documentation. Alphabetical. If a term is used anywhere in the docs without an inline explanation, it should appear here.

---

### BGE-large (`BAAI/bge-large-en-v1.5`)
The AI model this project uses to produce *semantic embeddings* — the "meaning-fingerprints" for documents and queries. Open source, free, 1024 numbers per piece of text, runs on a CPU. Published by the Beijing Academy of Artificial Intelligence (the "BAAI" in the model name). See also: *dense embeddings*, *semantic search*.

### BM25
A classic keyword-matching algorithm from the 1990s, still widely used because it's fast, cheap, and well-understood. Scores a document based on how many of the query's words appear in it, weighted by how rare those words are globally. Pure *keyword search* — no understanding of meaning. See also: *hybrid*, *semantic search*.

### Chunk
A searchable passage of text — typically a paragraph or a section of a document. Documents are too big to search as a whole (an 800-page statutory PDF is unusable as a single search result), so they are split into chunks during *ingest*. Each chunk carries metadata (source, URL, section reference, etc.) so results can be cited. This project has 8,691 chunks derived from 1,215 documents.

### Chunking / chunker
The process (and the module) that splits documents into chunks. This project implements two strategies:
- `FixedSizeChunker` — splits every N characters, ignoring structure (a baseline).
- `HeadingBoundaryChunker` — splits on detected section headings, which preserves the "§9.14" citation anchors statutory documents rely on. This is the default.

### Confidence gate
A rule in the answer-synthesis layer: if the top retrieved passage's score is below a threshold, skip the language model entirely and return a pre-written escalation message (pointing to IPSEA's helpline). Prevents the system from hallucinating on weak retrievals. The threshold is tunable. See also: *RAG*.

### Corpus
The full collection of documents a search system searches over. This project's corpus is 1,215 UK Special Educational Needs guidance documents drawn from five sources (SEND Code of Practice, gov.uk, DfE statistics, 15 Local Authorities, IPSEA + Contact).

### Cross-encoder / reranker
An AI model that takes a (query, passage) pair and scores how well they match by reading them together — distinct from *dense embeddings*, which score query and passage separately and then compare their fingerprints. More accurate in principle but much slower. Used as a second pass over the top 50 candidates from keyword+semantic fusion. This project uses `BAAI/bge-reranker-base`. On this corpus the reranker unexpectedly *hurt* quality (see REPORT).

### Dense embeddings
A list of numbers (1024 of them, in this project) that represents the meaning of a piece of text. Two texts about similar things will have similar embeddings (mathematically: their vectors point in similar directions). Produced by *BGE-large*. See also: *semantic search*.

### DfE
**Department for Education** — the UK government department responsible for education in England. Publishes statutory SEN guidance (the SEND Code of Practice), SEN statistics, and policy documents. One of the five source families in this corpus.

### EHCP (Education, Health and Care Plan)
The legal document that sets out the special educational, health, and care needs of a child or young person and what support the local authority must provide to meet them. Issued by the local authority after an *EHC needs assessment*. The focus of most of the real-parent-scenario queries in the eval set.

### Fusion (weighted / RRF)
Two ways of combining scores from BM25 (keyword) and dense (semantic) search when both return candidate passages:
- **Weighted-normalised-sum** — normalise each retriever's scores to the range [0, 1], then add them with tunable weights (default: 0.35 × BM25 + 0.65 × semantic). Exposes *why* a passage ranked highly.
- **RRF (Reciprocal Rank Fusion)** — ignore the scores, use only the ranks. Parameter-free and robust; used as a fallback.

### Ground truth / qrels
A hand-authored list of which passages in the corpus *should* be returned for each query, used as the correct-answer key during evaluation. "Qrels" = "query relevance judgments". In this project, ground truth is *matcher-based* — each query has a list of matchers (e.g. "source = gov.uk/send-cop AND section_ref starts with 9.") that are applied to the corpus to build the qrel list automatically, so the ground truth survives chunker-config changes.

### Hybrid (hybrid search, hybrid retrieval)
A search configuration that combines BM25 (keyword) and dense (semantic) scores via *fusion*. The intuition: keyword search catches exact phrase matches that semantic might miss, semantic catches meaning matches that keyword misses, and the fusion layer weights both. On this corpus, hybrid beats semantic-alone on 4 of 7 query types.

### Hybrid + rerank (`hybrid_rerank`)
A search configuration that runs hybrid first to get the top ~50 candidates, then uses a cross-encoder reranker to re-score and re-order them. Theoretically the most accurate, practically the slowest. On this corpus it *reduced* quality — see REPORT for the honest finding.

### Ingest / ingest pipeline
The data pipeline that fetches documents from their sources (gov.uk, LA websites, charity sites, PDFs), parses them, and produces uniform `Document` objects ready for chunking. Each source has its own adapter (`src/uk_sen_guide/sources/*.py`). Content is cached on disk so re-running doesn't re-fetch.

### IPSEA
**Independent Provider of Special Education Advice** (`ipsea.org.uk`) — the UK's leading charity offering free legal advice to parents of children with special educational needs. 399 IPSEA articles are ingested into this corpus. IPSEA's helpline (0800 018 4016) is where the confidence gate escalates low-confidence queries.

### JSONL (JSON Lines)
A simple data format: one JSON record per line of a text file. Used for the corpus chunks file (`chunks-<hash>.jsonl`) and for per-query eval outputs (`eval_runs/*.jsonl`). Human-readable, trivially parseable with standard tools like `jq`.

### LLM-as-judge
An evaluation technique where, instead of (or in addition to) pre-authored ground-truth labels, you use a language model to judge each retrieved passage for usefulness against the query. More expensive but closes the *metric-vs-usefulness gap* (see REPORT). Listed as a roadmap item.

### Local Offer
The catalogue every English local authority is required to publish describing the SEN support available in its area — schools, services, eligibility criteria, how to apply. 152 councils publish 152 Local Offers in 152 formats. This corpus ingests 484 Local Offer pages from 15 LAs.

### NDCG@5 (Normalised Discounted Cumulative Gain at 5)
A weighted search-quality score on a 0-to-1 scale. Rewards results that are *relevant and near the top*; penalises relevant results buried at rank 5 over relevant results at rank 1. Uses a `(2^rel − 1)` gain function and `log2(rank + 1)` position discount. "NDCG at 5" = computed only on the top 5 results. Standard in information retrieval research.

### p50 / p95 latency
Percentile response times:
- **p50** (median) — half of all queries finish faster than this.
- **p95** — 95% of queries finish faster than this; the slowest 5% are slower.
Used instead of "average" because averages hide tail latency, which is what users actually experience as "slow".

### Precision@5
Of the top 5 results the system returned for a query, what fraction were actually relevant? Higher = fewer wasted results in front of the user.

### Qdrant
An open-source vector database — the piece of software that stores the 1024-dimensional dense embeddings and runs fast nearest-neighbour search over them. Runs in Docker for this project. Alternative to Pinecone, Weaviate, or pgvector; chosen here for its native metadata filtering and reviewer reproducibility.

### qrels
See *ground truth*.

### RAG (Retrieval-Augmented Generation)
An architecture that feeds retrieved passages into a language model as context, so the model's answer is grounded in source documents it can cite. The synthesis layer in this project is a RAG implementation.

### Recall@5
Of all the relevant passages in the whole corpus for a query, what fraction did the top 5 results capture? With thousands of potentially relevant chunks per query, R@5 values are usually small; the ratio between configurations is what matters.

### Reranker
See *cross-encoder*.

### Retrieval
The act of finding the most relevant passages in a corpus given a query. Distinct from *generation*, where an AI model writes an answer. A RAG system does retrieval first, then uses the retrieved passages to guide generation. This project is primarily a retrieval platform.

### RRF (Reciprocal Rank Fusion)
See *fusion*.

### Section reference (`section_ref`)
A citation anchor like "9.14" (meaning "paragraph 9.14 of the SEND Code of Practice"). Preserved through chunking so retrieval results can be cited precisely. 91% preservation rate with the `HeadingBoundaryChunker`.

### SEN / SEND
- **SEN** — Special Educational Needs.
- **SEND** — Special Educational Needs and Disabilities (the "D" was added when the 2014 legal framework expanded to cover disabilities too).
Used roughly interchangeably in practice; "SEND" is the current statutory term.

### SEND Code of Practice
The statutory guidance (a 292-page PDF) that schools, local authorities, health services, and tribunals must "have regard to" under the Children and Families Act 2014. Covers every stage of SEN support — identification, EHCP process, placements, appeals. The foundational document of the corpus; split into 978 section-aware chunks.

### SEND Tribunal (formally: the First-tier Tribunal, Special Educational Needs and Disability)
The independent court that hears appeals against local authority decisions about SEN — refusal to assess, refusal to issue an EHCP, dispute over the plan's content, school placement disagreements. Familiarly: "the Tribunal". Success rate for families, per IPSEA: ~95%.

### Semantic search
Search that matches on meaning rather than exact words. See also: *dense embeddings*, *BGE-large*.

### Synthesis layer
The RAG component that takes the top retrieved passages and writes a natural-language answer with inline citations. Shipped in this project as a demonstrator; not evaluated as part of the graded submission. Five response states: `high`, `medium`, `low`, `llm_error`, `out_of_scope`.
