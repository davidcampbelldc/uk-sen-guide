"""Retrieval metric computation — precision@k, recall@k, NDCG@k.

Implemented directly rather than via ranx (single clear source of truth for
exactly what we're measuring). All metrics take qrels (ground-truth
chunk_id → graded relevance) and a ranked list (chunk_ids) as input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class QueryMetrics:
    query_id: str
    precision_at_5: float = 0.0
    recall_at_5: float = 0.0
    ndcg_at_5: float = 0.0


@dataclass
class AggregateMetrics:
    per_query: list[QueryMetrics] = field(default_factory=list)

    @property
    def mean_precision_at_5(self) -> float:
        return _mean([m.precision_at_5 for m in self.per_query])

    @property
    def mean_recall_at_5(self) -> float:
        return _mean([m.recall_at_5 for m in self.per_query])

    @property
    def mean_ndcg_at_5(self) -> float:
        return _mean([m.ndcg_at_5 for m in self.per_query])


def precision_at_k(ranked: list[str], qrels: dict[str, int], k: int) -> float:
    if k <= 0:
        return 0.0
    top = ranked[:k]
    if not top:
        return 0.0
    rel = sum(1 for cid in top if qrels.get(cid, 0) > 0)
    return rel / k


def recall_at_k(ranked: list[str], qrels: dict[str, int], k: int) -> float:
    total_relevant = sum(1 for grade in qrels.values() if grade > 0)
    if total_relevant == 0:
        return 0.0
    top = ranked[:k]
    got = sum(1 for cid in top if qrels.get(cid, 0) > 0)
    return got / total_relevant


def ndcg_at_k(ranked: list[str], qrels: dict[str, int], k: int) -> float:
    if k <= 0:
        return 0.0
    dcg = 0.0
    for i, cid in enumerate(ranked[:k]):
        grade = qrels.get(cid, 0)
        if grade > 0:
            # Standard gain function — (2^rel - 1)
            gain = (2 ** grade) - 1
            dcg += gain / math.log2(i + 2)  # rank positions are 1-indexed
    # Ideal DCG — sort qrels by grade descending, take top-k
    ideal = sorted(qrels.values(), reverse=True)[:k]
    idcg = 0.0
    for i, grade in enumerate(ideal):
        if grade > 0:
            gain = (2 ** grade) - 1
            idcg += gain / math.log2(i + 2)
    if idcg == 0:
        return 0.0
    return dcg / idcg


def evaluate_one(query_id: str, ranked: list[str], qrels: dict[str, int]) -> QueryMetrics:
    return QueryMetrics(
        query_id=query_id,
        precision_at_5=precision_at_k(ranked, qrels, 5),
        recall_at_5=recall_at_k(ranked, qrels, 5),
        ndcg_at_5=ndcg_at_k(ranked, qrels, 5),
    )


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0
