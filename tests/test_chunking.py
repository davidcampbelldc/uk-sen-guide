"""Chunker tests — verify invariants across strategies."""

from datetime import datetime, timezone

from senlit_retrieval.chunking import FixedSizeChunker, HeadingBoundaryChunker
from senlit_retrieval.models import Document, Section, SourceMetadata


def _make_doc(body: str, sections: list[Section] | None = None) -> Document:
    meta = SourceMetadata(
        source="test",
        source_id="t1",
        fetched_at=datetime.now(timezone.utc),
        url=None,
        licence="test",
    )
    return Document(
        doc_id="test::t1",
        title="Test",
        body=body,
        sections=sections or [],
        metadata=meta,
        content_hash="deadbeef",
    )


def test_fixed_chunker_handles_short_body():
    doc = _make_doc("hello world")
    chunks = FixedSizeChunker(max_chars=100, overlap_chars=10).chunk(doc)
    assert len(chunks) == 1
    assert chunks[0].text == "hello world"
    assert chunks[0].section_ref is None


def test_fixed_chunker_splits_with_overlap():
    body = "a" * 250
    chunks = FixedSizeChunker(max_chars=100, overlap_chars=20).chunk(_make_doc(body))
    assert len(chunks) >= 3
    for a, b in zip(chunks, chunks[1:]):
        # Each subsequent chunk starts before the previous one ends.
        assert b.char_start < a.char_end


def test_fixed_chunker_produces_unique_ids():
    body = "a" * 1000
    chunks = FixedSizeChunker(max_chars=100, overlap_chars=20).chunk(_make_doc(body))
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


def test_heading_boundary_falls_back_without_sections():
    doc = _make_doc("x" * 100)
    chunks = HeadingBoundaryChunker(target_chars=50).chunk(doc)
    assert len(chunks) >= 1


def test_heading_boundary_preserves_section_refs():
    body = ("a" * 100) + ("b" * 100) + ("c" * 100)
    sections = [
        Section(ref="1.1", heading="A", start_char=0, end_char=100, depth=1),
        Section(ref="1.2", heading="B", start_char=100, end_char=200, depth=1),
        Section(ref="1.3", heading="C", start_char=200, end_char=300, depth=1),
    ]
    doc = _make_doc(body, sections=sections)
    chunks = HeadingBoundaryChunker(target_chars=200, hard_max_chars=200).chunk(doc)
    refs = {c.section_ref for c in chunks}
    assert refs == {"1.1", "1.2", "1.3"}


def test_heading_boundary_splits_oversize_section():
    body = "z" * 10_000
    sections = [
        Section(ref="99.1", heading="Big", start_char=0, end_char=10_000, depth=1),
    ]
    doc = _make_doc(body, sections=sections)
    chunks = HeadingBoundaryChunker(
        target_chars=2000, hard_max_chars=3000, overlap_chars=200
    ).chunk(doc)
    assert len(chunks) >= 4
    # All inherit the section ref
    assert all(c.section_ref == "99.1" for c in chunks)


def test_chunker_config_hash_stable_and_sensitive():
    a = FixedSizeChunker(max_chars=500, overlap_chars=50).config_dict()
    b = FixedSizeChunker(max_chars=500, overlap_chars=50).config_dict()
    c = FixedSizeChunker(max_chars=800, overlap_chars=50).config_dict()
    assert a == b
    assert a != c
