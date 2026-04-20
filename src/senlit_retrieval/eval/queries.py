"""Eval query schema and loader.

Queries live in a YAML file (or JSONL). Each query has:
  id:          stable identifier (e.g. "q001")
  type:        query category — statutory-citation / symptom-driven / process / ...
  query:       the natural-language query string
  relevant:    list of ground-truth matchers with graded relevance (0, 1, 2)

Ground-truth matchers are open-schema dicts against chunk metadata. A chunk
is considered relevant at the declared grade if every key in the matcher
equals the corresponding value on the chunk (source, section_ref, local_authority,
doc_id substring, etc.). This lets us grade by section number for statutory
content, by LA for Local Offer queries, and by keyword-in-metadata otherwise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Matcher:
    conditions: dict[str, Any]        # e.g. {"source": "gov.uk/send-cop", "section_ref": "1.1"}
    relevance: int                    # 0 / 1 / 2

    def matches(self, chunk_meta: dict[str, Any], *, section_ref: str | None, doc_id: str | None) -> bool:
        for k, v in self.conditions.items():
            if k == "section_ref":
                if section_ref is None or section_ref != v:
                    return False
            elif k == "section_ref_prefix":
                # Matches whole chapters: prefix "9." matches 9.1, 9.2, 9.100 etc.
                if section_ref is None or not section_ref.startswith(str(v)):
                    return False
            elif k == "doc_id_contains":
                if doc_id is None or str(v) not in doc_id:
                    return False
            elif k == "text_contains":
                # Single string → substring match.
                # List → all items must appear (AND semantics, tight anchoring).
                text = chunk_meta.get("text", "").lower()
                if isinstance(v, (list, tuple)):
                    if not all(str(item).lower() in text for item in v):
                        return False
                else:
                    if str(v).lower() not in text:
                        return False
            else:
                if chunk_meta.get(k) != v:
                    return False
        return True


@dataclass(frozen=True)
class Query:
    id: str
    type: str
    query: str
    matchers: tuple[Matcher, ...] = field(default_factory=tuple)

    @property
    def qrels(self) -> dict[str, int]:
        """Just the declared relevant items mapped to relevance grade — used for per-query max.

        Actual per-chunk qrels are computed by scanning the chunk corpus against each matcher.
        """
        return {f"m{i}": m.relevance for i, m in enumerate(self.matchers)}


def load_queries(path: Path) -> list[Query]:
    raw = yaml.safe_load(path.read_text())
    out: list[Query] = []
    for item in raw.get("queries", []):
        matchers = tuple(
            Matcher(conditions=dict(m.get("match", {})), relevance=int(m.get("relevance", 1)))
            for m in item.get("relevant", [])
        )
        out.append(Query(
            id=str(item["id"]),
            type=str(item.get("type", "general")),
            query=str(item["query"]),
            matchers=matchers,
        ))
    return out


def load_chunks_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
