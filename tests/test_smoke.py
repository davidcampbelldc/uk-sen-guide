"""Smoke test: package imports cleanly."""

import uk_sen_guide


def test_version_available():
    assert uk_sen_guide.__version__
