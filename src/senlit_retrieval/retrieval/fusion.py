"""Score fusion for hybrid retrieval.

Two strategies implemented:

* **Weighted normalized sum** — min-max normalise each retriever's scores to
  [0,1], then combine with tunable weights. Interpretable and tunable.
* **Reciprocal Rank Fusion (RRF)** — rank-based, parameter-free, robust to
  score-scale differences. Backup / alternative ranking.

The weighted-normalized-sum is the default. RRF is exposed as an
alternative fusion mode in the API.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _normalise(scores: list[float]) -> list[float]:
    if not scores:
        return []
    lo = min(scores)
    hi = max(scores)
    if hi - lo < 1e-9:
        return [0.5 for _ in scores]
    return [(s - lo) / (hi - lo) for s in scores]


def weighted_fuse(
    bm25_hits: list[tuple[str, float]],
    dense_hits: list[tuple[str, float, dict[str, Any]]],
    bm25_weight: float = 0.35,
    dense_weight: float = 0.65,
    top_k: int = 50,
) -> list[tuple[str, float, dict[str, float]]]:
    """Fuse BM25 and dense hits with weighted normalized scoring.

    Returns a list of (chunk_id, fused_score, score_breakdown), sorted desc.
    score_breakdown contains the per-retriever contributions (normalised).
    """
    bm25_scores = _normalise([s for _, s in bm25_hits])
    dense_scores = _normalise([s for _, s, _ in dense_hits])

    bm25_by_id = {cid: bm25_scores[i] for i, (cid, _) in enumerate(bm25_hits)}
    dense_by_id = {cid: dense_scores[i] for i, (cid, _, _) in enumerate(dense_hits)}

    all_ids = set(bm25_by_id) | set(dense_by_id)
    out: list[tuple[str, float, dict[str, float]]] = []
    for cid in all_ids:
        b = bm25_by_id.get(cid, 0.0)
        d = dense_by_id.get(cid, 0.0)
        fused = bm25_weight * b + dense_weight * d
        out.append((cid, fused, {"bm25": b, "semantic": d}))
    out.sort(key=lambda t: t[1], reverse=True)
    return out[:top_k]


def rrf_fuse(
    bm25_hits: list[tuple[str, float]],
    dense_hits: list[tuple[str, float, dict[str, Any]]],
    k: int = 60,
    top_k: int = 50,
) -> list[tuple[str, float, dict[str, float]]]:
    """Reciprocal Rank Fusion — 1/(k + rank). Parameter-free, robust."""
    ranks: dict[str, dict[str, int]] = defaultdict(dict)
    for rank, (cid, _) in enumerate(bm25_hits):
        ranks[cid]["bm25"] = rank + 1
    for rank, (cid, _, _) in enumerate(dense_hits):
        ranks[cid]["semantic"] = rank + 1

    out: list[tuple[str, float, dict[str, float]]] = []
    for cid, rank_map in ranks.items():
        contributions = {src: 1.0 / (k + rank) for src, rank in rank_map.items()}
        fused = sum(contributions.values())
        out.append((cid, fused, contributions))
    out.sort(key=lambda t: t[1], reverse=True)
    return out[:top_k]
