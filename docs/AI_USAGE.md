---
title: "AI collaboration note: authorship and verification of AI-assisted work"
date: 2026-04-20
status: PARTIAL
question: "Which parts of the project were written by Claude Code versus the author, and how was the AI's output reviewed and verified?"
topic: docs
backfilled: 2026-10-05
---

# AI Collaboration Note

LEC's brief: *"be honest: which parts did Claude Code / other AI write,
which parts are yours, how you verified what the AI produced."*

## Tool used

This repository was built in pair-programming mode with **Claude Code**
(Anthropic's CLI agent for software engineering), using Claude Opus 4.7.
Sessions were interactive — I directed the work, Claude wrote the bulk
of the code, I reviewed every commit and made the architectural and
evaluation-methodology calls.

## What I owned

- **Assignment choice.** I picked Assignment 1 after weighing all three
  against what I could ship to a production bar in three days.
  Reasoning is recorded in the architecture doc. The choice is
  defensible on its engineering merits alone; the fact that I was also
  interested in building a SEN retrieval layer as a side-project gave
  the work real stakes.
- **Architecture decisions.** Qdrant over OpenSearch + Bedrock (for
  reviewer reproducibility), BGE-large over paid embedding APIs
  (reproducibility + cost), direct metric implementation over `ranx`
  (transparency about what is measured). These are my calls;
  alternatives and trade-offs are documented in `docs/architecture.md`.
- **Corpus strategy.** Choice of sources (statutory + DfE + LA + charity
  mix), choice of 15 LAs to sample, decision to treat XLSX as the
  real-world CSV-equivalent, decision to handle one-doc-per-CSV with a
  text description rather than one-doc-per-row. Each is justified in
  the architecture doc.
- **Evaluation methodology.** Graded matcher-based qrels; 0/1/2 relevance
  scale with (2^rel − 1) gain; seven query types spanning statutory
  citation / symptom-driven / process / timing / rights-refusal /
  real-parent-scenario / out-of-scope; direct implementation of P@5,
  R@5, NDCG@5. I authored every query and every ground-truth matcher.
- **Discipline calls.** SEN-relevance filter (precision over recall in
  the corpus), per-LA metadata schema (forward-compat for a future LA
  filter), reviewer-reproducibility as a first-class constraint
  (reflects in infra choices throughout).
- **Interpretation of eval results.** The per-config and per-query-type
  numbers in the report are real measurements; the narrative around
  them — what they mean, what they don't, what surprised me — is mine.

## What Claude wrote

- **Most code.** Claude drafted the ingest adapters, the retrieval
  modules (BM25, dense, reranker, fusion, search), the FastAPI server,
  the eval harness, the load test. I reviewed each file, pushed back
  where the design needed it, and accepted the rest.
- **Boilerplate.** pyproject.toml, docker-compose.yml, .gitignore,
  tests, the initial README skeleton. Standard stuff.
- **Docstrings and comments.** Claude wrote these with prompting to
  focus on *why* rather than *what*. I edited where tone or emphasis
  was off.

## AI use that directly affects the artefact

Two things a reviewer should weigh separately from the "Claude as coding
tool" default:

1. **Eval query candidate generation.** Claude generated candidate
   queries for me to review; I kept, edited, or rejected each. The
   current 43-query set is the subset I kept after review — every
   query survived because it either reflects a real parent question I
   could imagine being asked or tests a specific corner of retrieval
   behaviour (statutory citation matching, out-of-scope behaviour, etc.).
   The 8 "real-parent-scenario" queries are mine, written from lived
   experience of a SEND Tribunal refusal-to-assess appeal — anonymised,
   no identifying details. Ground-truth matchers are mine throughout:
   I decided which sources and section anchors count as relevant for
   each query. I did not ask Claude to generate ground truth.
2. **Relevance-filter tuning.** The list of SEN-markers used to filter
   off-topic pages from gov.uk search results (`special educational
   need`, `ehcp`, `local offer`, etc.) was brainstormed collaboratively,
   iterated against observed false positives (passport pages, driving
   licence guidance), and finalised by me. The filter's precision
   bias is an intentional choice: off-topic pages in the corpus would
   degrade both retrieval quality and eval signal.

## What I verified

- **Every commit.** I reviewed every change before it landed on `main`.
  When Claude wrote broken logic — for example, the first CSV adapter
  didn't account for modern DfE publishing XLSX instead of CSV — I
  caught the behaviour in pilot runs and redirected.
- **Syntax + tests after every change.** `python3 -c "import ast"` on
  new files, `pytest -q` on the full suite before each commit.
- **Pilot runs after each adapter.** The ingest pipeline was smoke-run
  after each new source adapter landed, with a sampled document
  printed to verify content quality and metadata correctness. Noise
  was caught and filtered out (the SEN-relevance filter was the
  result).
- **Clean-room hygiene.** A pre-commit hook blocks `Co-Authored-By:
  Claude` trailers and prevents accidental leakage of internal-project
  references; every commit was vetted through it before hitting
  `main`.

## What surprised me

- The gov.uk public search API returns *remarkably off-topic* results
  for "SEN" queries if you don't filter (UK passport renewal showing
  up for "SEN school" was a genuine moment of "wait, really?").
  Relevance-filter precision matters more than I initially expected.
- The Local Authority variance problem is more severe than I thought.
  Of 16 LAs sampled, coverage ranges from 3 docs (Leicester, Hackney)
  to 80 docs (Lewisham, Brighton, Oxfordshire). Same statutory
  requirement, wildly different implementations. This is the single
  biggest real-world-deployment concern for any serious SEN knowledge
  tool.
- pypdf's section-detection via regex on SEND CoP numbered paragraphs
  (e.g. "1.1", "11.45") works better than I expected — 947 sections
  recovered cleanly from a 292-page statutory PDF, each usable as a
  citation anchor.

## On honesty

Claude Code is a very capable coding partner. Much of the raw code here
would have been slower to produce without it. But the decisions — what
to build, what to reject, how to evaluate, how to frame the writeup —
are mine, and are where the judgment signal lives. A reviewer evaluating
this submission should read the code as a joint artefact and the
decisions as mine. That distinction is load-bearing.
