"""Metric computation tests."""

from senlit_retrieval.eval.metrics import (
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_precision_at_k_perfect():
    ranked = ["a", "b", "c", "d", "e"]
    qrels = {"a": 2, "b": 2, "c": 1, "d": 1, "e": 2}
    assert precision_at_k(ranked, qrels, 5) == 1.0


def test_precision_at_k_partial():
    ranked = ["a", "x", "c", "y", "e"]
    qrels = {"a": 2, "c": 1, "e": 2}
    assert precision_at_k(ranked, qrels, 5) == 0.6


def test_precision_at_k_none_relevant():
    ranked = ["x", "y", "z"]
    qrels = {"a": 1}
    assert precision_at_k(ranked, qrels, 5) == 0.0


def test_recall_at_k_all_found():
    ranked = ["a", "b", "c", "d", "e"]
    qrels = {"a": 2, "c": 1}
    assert recall_at_k(ranked, qrels, 5) == 1.0


def test_recall_at_k_partial():
    ranked = ["a", "x", "y", "z", "w"]
    qrels = {"a": 2, "b": 1, "c": 1, "d": 1}
    assert recall_at_k(ranked, qrels, 5) == 0.25


def test_ndcg_at_k_ideal_order():
    ranked = ["a", "b", "c"]
    qrels = {"a": 2, "b": 2, "c": 1}
    assert ndcg_at_k(ranked, qrels, 5) == 1.0


def test_ndcg_at_k_wrong_order_penalises():
    good = ndcg_at_k(["a", "b"], {"a": 2, "b": 1}, 5)
    bad = ndcg_at_k(["b", "a"], {"a": 2, "b": 1}, 5)
    assert good > bad
    assert 0 < bad < good


def test_ndcg_at_k_empty_qrels():
    assert ndcg_at_k(["a", "b"], {}, 5) == 0.0
