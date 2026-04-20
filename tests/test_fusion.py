"""Fusion strategy tests."""

from senlit_retrieval.retrieval.fusion import rrf_fuse, weighted_fuse


def test_weighted_fuse_prefers_consensus():
    # Same chunk scored well by both retrievers should rank top
    bm25 = [("a", 10.0), ("b", 9.0), ("c", 8.0)]
    dense = [("a", 0.9, {}), ("b", 0.5, {}), ("d", 0.3, {})]
    fused = weighted_fuse(bm25, dense, top_k=4)
    assert fused[0][0] == "a"
    # Score breakdown preserved
    assert set(fused[0][2].keys()) == {"bm25", "semantic"}


def test_weighted_fuse_respects_weights():
    bm25 = [("x", 10.0), ("y", 1.0)]
    dense = [("y", 0.9, {}), ("x", 0.1, {})]
    # Heavily weight dense — y should win
    fused = weighted_fuse(bm25, dense, bm25_weight=0.1, dense_weight=0.9, top_k=2)
    assert fused[0][0] == "y"


def test_weighted_fuse_handles_disjoint_sets():
    bm25 = [("a", 10.0), ("b", 9.0)]
    dense = [("c", 0.9, {}), ("d", 0.5, {})]
    fused = weighted_fuse(bm25, dense, top_k=4)
    chunk_ids = {cid for cid, _, _ in fused}
    assert chunk_ids == {"a", "b", "c", "d"}


def test_rrf_fuse_is_parameter_free():
    bm25 = [("a", 10.0), ("b", 9.0), ("c", 8.0)]
    dense = [("b", 0.9, {}), ("a", 0.5, {}), ("d", 0.3, {})]
    fused = rrf_fuse(bm25, dense, top_k=4)
    # 'a' appears at ranks 1,2 and 'b' at ranks 2,1 — both should beat others
    top_ids = {cid for cid, _, _ in fused[:2]}
    assert top_ids == {"a", "b"}


def test_weighted_fuse_normalises_scale_differences():
    # BM25 raw scores can be in tens/hundreds; cosine similarity is 0-1.
    # After normalisation, both retrievers should contribute comparably.
    bm25 = [("a", 500.0), ("b", 250.0)]
    dense = [("a", 0.8, {}), ("b", 0.4, {})]
    fused = weighted_fuse(bm25, dense, bm25_weight=0.5, dense_weight=0.5, top_k=2)
    # 'a' at top, 'b' second — order matches both retrievers
    assert [cid for cid, _, _ in fused] == ["a", "b"]
    # Normalised scores for 'a' should be close to 1.0 from each side
    assert fused[0][2]["bm25"] > 0.9
    assert fused[0][2]["semantic"] > 0.9
