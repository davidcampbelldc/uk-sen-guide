"""Cross-encoder reranker.

`BAAI/bge-reranker-base` — small (~278M params), CPU-runnable, well-behaved
on BEIR. Loaded lazily on first call; scores query/candidate pairs and
returns a new ordering.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_RERANKER = "BAAI/bge-reranker-base"


class CrossEncoderReranker:
    def __init__(self, model_name: str = DEFAULT_RERANKER):
        self.model_name = model_name
        self._model = None

    def _ensure(self) -> None:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            log.info("loading reranker model %s", self.model_name)
            self._model = CrossEncoder(self.model_name)

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[tuple[dict[str, Any], float]]:
        """Rerank candidates by (query, candidate.text) cross-encoder score.

        Returns candidates annotated with reranker score, sorted descending,
        truncated to top_k. Score is raw cross-encoder logit (float).
        """
        if not candidates:
            return []
        self._ensure()
        assert self._model is not None
        pairs = [(query, c["text"]) for c in candidates]
        scores = self._model.predict(pairs, show_progress_bar=False).tolist()
        ranked = sorted(
            zip(candidates, scores),
            key=lambda t: t[1],
            reverse=True,
        )
        return ranked[:top_k]
