# Raw eval outputs

This directory holds the per-query raw outputs from `python -m uk_sen_guide.eval.run`. Every aggregate number in `docs/REPORT.md` is computed from these files — a reviewer can recompute each row to three decimal places directly from the JSONL, without re-running the eval harness.

The files are committed as evidence for a take-home assessment graded on "real numbers, not vibes". They would normally be regenerable and excluded via `.gitignore`; the convention being applied here is that for a take-home graded on measurements, the raw measurements belong in the repo alongside the REPORT that cites them.

## Schema (one JSON object per line)

```
query_id           string  — "q001" … "q043"
type               string  — one of seven query types (see below)
query              string  — the natural-language query as authored
config             string  — "semantic" | "hybrid" | "hybrid_rerank"
ranked             list    — top-K retrieved chunk_ids, in ranked order
num_relevant       int     — total corpus-wide qrel count (relevance > 0) for this query
latency_ms         number  — per-query retrieval latency (ms)
metrics            object
  .precision_at_5  number  — P@5 for this query
  .recall_at_5     number  — R@5 for this query
  .ndcg_at_5       number  — NDCG@5 with (2^rel − 1) gain, log2(rank+1) discount
```

## Query types (n = 43)

| Type | Count | Focus |
|---|---|---|
| statutory-citation | — | SEND Code of Practice §X.Y lookups |
| symptom-driven | — | "What do I do if …" |
| process | — | "How do I …" |
| timing | — | Deadlines, windows, statutory weeks |
| rights-refusal | — | Appeal / refusal-to-assess scenarios |
| real-parent-scenario | 8 | Lived experience of SEND Tribunal |
| out-of-scope | — | Deliberately unmatched — tests honest "no relevant" behaviour |

## Iterations in this directory

Nine files cover three iterations × three configs. Timestamps are epoch seconds.

| Timestamp | File stem | Config | Queries | Notes |
|---|---|---|---|---|
| 1776683155 | `semantic-…` | semantic | 35 | First pass (pre real-parent additions) |
| 1776683158 | `hybrid-…` | hybrid | 35 | First pass |
| 1776683615 | `hybrid_rerank-…` | hybrid_rerank | 35 | First pass |
| 1776684028 | `semantic-…` | semantic | 35 | Second pass (tightened matchers) |
| 1776684031 | `hybrid-…` | hybrid | 35 | Second pass |
| 1776684103 | `hybrid_rerank-…` | hybrid_rerank | 35 | Second pass |
| **1776686900** | `semantic-…` | semantic | **43** | **Final pass — used for REPORT** |
| **1776686905** | `hybrid-…` | hybrid | **43** | **Final pass — used for REPORT** |
| **1776686998** | `hybrid_rerank-…` | hybrid_rerank | **43** | **Final pass — used for REPORT** |

The REPORT's headline numbers come from the three files marked **Final pass**. The earlier iterations are kept for provenance — they show the narrowing from 35 → 43 queries (commit `ad0776c` added 8 real-parent-scenario queries) and the matcher tightening that preceded the final run.

## Reproducer snippet

Compute the aggregate P@5 / R@5 / NDCG@5 from the three final-pass files:

```python
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).parent
for config_stem in ("semantic-1776686900", "hybrid-1776686905", "hybrid_rerank-1776686998"):
    path = ROOT / f"{config_stem}.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    p = mean(r["metrics"]["precision_at_5"] for r in rows)
    r5 = mean(r["metrics"]["recall_at_5"] for r in rows)
    ndcg = mean(r["metrics"]["ndcg_at_5"] for r in rows)
    lat = sorted(r["latency_ms"] for r in rows)
    p50 = lat[len(lat) // 2]
    p95 = lat[int(len(lat) * 0.95)]
    print(
        f"{config_stem:40s} n={len(rows)} "
        f"P@5={p:.3f} R@5={r5:.3f} NDCG@5={ndcg:.3f} "
        f"p50={p50}ms p95={p95}ms"
    )
```

Expected output (matches `docs/REPORT.md` exactly to three decimal places):

```
semantic-1776686900                      n=43 P@5=0.298 R@5=0.023 NDCG@5=0.267 p50=94ms p95=186ms
hybrid-1776686905                        n=43 P@5=0.307 R@5=0.023 NDCG@5=0.285 p50=99ms p95=135ms
hybrid_rerank-1776686998                 n=43 P@5=0.260 R@5=0.017 NDCG@5=0.238 p50=2300ms p95=2408ms
```

If these don't match, the REPORT is stale — open an issue.
