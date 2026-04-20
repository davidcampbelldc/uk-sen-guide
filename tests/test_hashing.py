"""Hashing tests — stability, sensitivity, and composition."""

from uk_sen_guide.hashing import chunk_id, doc_id, hash_config, hash_text


def test_hash_text_deterministic():
    assert hash_text("hello world") == hash_text("hello world")


def test_hash_text_sensitive():
    assert hash_text("a") != hash_text("b")
    assert hash_text("a", salt="x") != hash_text("a", salt="y")


def test_hash_text_short():
    assert len(hash_text("x")) == 16


def test_hash_config_key_order_invariant():
    a = {"x": 1, "y": 2}
    b = {"y": 2, "x": 1}
    assert hash_config(a) == hash_config(b)


def test_hash_config_sensitive():
    assert hash_config({"x": 1}) != hash_config({"x": 2})


def test_doc_id_stable():
    assert doc_id("src", "doc-1") == doc_id("src", "doc-1")


def test_doc_id_changes_with_source():
    assert doc_id("a", "doc-1") != doc_id("b", "doc-1")


def test_chunk_id_formats_seq_with_zero_pad():
    cid = chunk_id("source::abc", 3)
    assert cid.endswith("::0003")


def test_chunk_id_with_section_ref():
    cid = chunk_id("source::abc", 3, "11.45")
    assert "11.45" in cid


def test_chunk_id_normalises_unsafe_chars():
    cid = chunk_id("source::abc", 3, "11 / 45")
    assert "/" not in cid
    assert " " not in cid
