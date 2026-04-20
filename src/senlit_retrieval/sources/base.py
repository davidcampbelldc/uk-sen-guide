"""Source adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

from ..models import Document


class SourceAdapter(ABC):
    """Pull documents from a single source (gov.uk, DfE, IPSEA, ...).

    Implementations are responsible for:
      * Fetching content (cached in cache_dir to respect provider bandwidth)
      * Parsing (PDF/HTML/CSV → plain text + structure)
      * Producing stable doc_id and content_hash
      * Setting correct licence metadata

    Incremental semantics: running .documents() repeatedly against the same
    cache_dir should be idempotent and fast when upstream content is unchanged.
    """

    # Class-level metadata (subclasses must set)
    source: str
    licence: str

    @abstractmethod
    def documents(self, cache_dir: Path) -> Iterable[Document]:
        raise NotImplementedError
