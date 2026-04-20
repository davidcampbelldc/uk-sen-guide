"""Core data models for UK SEN Guide.

Open-schema metadata throughout — V2 will add filters for local authority,
age band, condition, and document type without schema migrations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SourceMetadata(BaseModel):
    """Per-source provenance attached to every document."""

    source: str                          # "gov.uk/send-cop", "dfe", "ipsea", ...
    source_id: str                       # stable identifier within source (URL path, doc code)
    fetched_at: datetime
    url: str | None = None
    licence: str                         # "OGL-3.0", "attribution", "public-record"
    extras: dict[str, Any] = Field(default_factory=dict)
    # ^ open-schema for V2: local_authority, age_band, condition, doc_type, etc.


class Section(BaseModel):
    """A structural section detected within a document (heading + body span)."""

    ref: str                             # "11.45" or "Chapter 5 > Introduction"
    heading: str
    start_char: int
    end_char: int
    depth: int = 1                       # 1 = top-level, 2 = subsection, ...


class Document(BaseModel):
    """A single ingested document after parsing."""

    doc_id: str                          # stable: hash of source + source_id
    title: str
    body: str                            # extracted plain text (UTF-8)
    sections: list[Section] = Field(default_factory=list)
    metadata: SourceMetadata
    content_hash: str                    # hash of body + sections (for incremental re-chunk)


class Chunk(BaseModel):
    """A chunk ready for embedding + indexing."""

    chunk_id: str                        # doc_id::seq or doc_id::seq::section_ref
    doc_id: str
    seq: int                             # 0-indexed position within document
    text: str
    section_ref: str | None = None       # for citations, e.g. "SEND CoP §11.45"
    token_count: int                     # approximate
    char_start: int
    char_end: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    # ^ denormalised source metadata + chunk-specific (chunker_arm, etc.)
    content_hash: str                    # hash of text + metadata (for incremental re-embed)
