"""Chunking strategies.

Three arms are implemented so the eval can compare them fairly:

  * FixedSizeChunker       — structure-blind baseline
  * HeadingBoundaryChunker — respects section structure (primary)
  * ParentChildChunker     — small chunks retrieved, larger parents returned

Token counts are approximated by char/4 (English rule of thumb). The eval
uses the same approximation across all arms so it's an apples-to-apples
comparison; the absolute number isn't meaningful.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .hashing import chunk_id, hash_text
from .models import Chunk, Document


def approx_tokens(text: str) -> int:
    """Rough English approximation — 1 token ≈ 4 characters."""
    return max(1, len(text) // 4)


class Chunker(ABC):
    """Abstract chunker."""

    name: str

    @abstractmethod
    def chunk(self, doc: Document) -> list[Chunk]:
        raise NotImplementedError

    @abstractmethod
    def config_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    def _build_chunk(
        self,
        doc: Document,
        text: str,
        seq: int,
        start: int,
        end: int,
        section_ref: str | None,
        extra_meta: dict[str, Any] | None = None,
    ) -> Chunk:
        meta: dict[str, Any] = {
            "source": doc.metadata.source,
            "licence": doc.metadata.licence,
            "chunker": self.name,
        }
        meta.update(doc.metadata.extras)
        if extra_meta:
            meta.update(extra_meta)
        cid = chunk_id(doc.doc_id, seq, section_ref)
        return Chunk(
            chunk_id=cid,
            doc_id=doc.doc_id,
            seq=seq,
            text=text,
            section_ref=section_ref,
            token_count=approx_tokens(text),
            char_start=start,
            char_end=end,
            metadata=meta,
            content_hash=hash_text(text, salt=cid),
        )


class FixedSizeChunker(Chunker):
    """Structure-blind fixed-size windows with overlap."""

    name = "fixed"

    def __init__(self, max_chars: int = 2000, overlap_chars: int = 200):
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk(self, doc: Document) -> list[Chunk]:
        chunks: list[Chunk] = []
        text = doc.body
        step = max(1, self.max_chars - self.overlap_chars)
        i = 0
        seq = 0
        while i < len(text):
            end = min(i + self.max_chars, len(text))
            piece = text[i:end]
            if piece.strip():
                chunks.append(
                    self._build_chunk(
                        doc,
                        piece,
                        seq,
                        i,
                        end,
                        section_ref=None,
                        extra_meta={
                            "max_chars": self.max_chars,
                            "overlap_chars": self.overlap_chars,
                        },
                    )
                )
                seq += 1
            if end == len(text):
                break
            i += step
        return chunks

    def config_dict(self) -> dict[str, Any]:
        return {
            "chunker": self.name,
            "max_chars": self.max_chars,
            "overlap_chars": self.overlap_chars,
        }


class HeadingBoundaryChunker(Chunker):
    """Breaks on heading boundaries. Splits oversize sections with overlap.

    Falls back to FixedSizeChunker when a document carries no structure.
    """

    name = "heading_boundary"

    def __init__(
        self,
        target_chars: int = 2400,       # ~600 tokens
        hard_max_chars: int = 3200,     # ~800 tokens
        overlap_chars: int = 400,       # ~100 tokens
    ):
        self.target_chars = target_chars
        self.hard_max_chars = hard_max_chars
        self.overlap_chars = overlap_chars

    def chunk(self, doc: Document) -> list[Chunk]:
        if not doc.sections:
            fallback = FixedSizeChunker(
                max_chars=self.target_chars, overlap_chars=self.overlap_chars
            )
            return fallback.chunk(doc)

        chunks: list[Chunk] = []
        seq = 0
        extra = {
            "target_chars": self.target_chars,
            "hard_max_chars": self.hard_max_chars,
            "overlap_chars": self.overlap_chars,
        }

        for section in doc.sections:
            section_text = doc.body[section.start_char : section.end_char]
            if not section_text.strip():
                continue

            if len(section_text) <= self.hard_max_chars:
                chunks.append(
                    self._build_chunk(
                        doc,
                        section_text,
                        seq,
                        section.start_char,
                        section.end_char,
                        section_ref=section.ref,
                        extra_meta={**extra, "section_heading": section.heading},
                    )
                )
                seq += 1
            else:
                # Split oversize section with overlap
                i = section.start_char
                step = max(1, self.target_chars - self.overlap_chars)
                while i < section.end_char:
                    end = min(i + self.target_chars, section.end_char)
                    piece = doc.body[i:end]
                    if piece.strip():
                        chunks.append(
                            self._build_chunk(
                                doc,
                                piece,
                                seq,
                                i,
                                end,
                                section_ref=section.ref,
                                extra_meta={**extra, "section_heading": section.heading},
                            )
                        )
                        seq += 1
                    if end == section.end_char:
                        break
                    i += step

        return chunks

    def config_dict(self) -> dict[str, Any]:
        return {
            "chunker": self.name,
            "target_chars": self.target_chars,
            "hard_max_chars": self.hard_max_chars,
            "overlap_chars": self.overlap_chars,
        }
