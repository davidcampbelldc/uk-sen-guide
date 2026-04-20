"""Smoke test: package imports cleanly."""

import senlit_retrieval


def test_version_available():
    assert senlit_retrieval.__version__
