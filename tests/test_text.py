from __future__ import annotations

from tide_mem.text import fts_query


def test_fts_query_adds_lightweight_morphology_variants():
    expression = fts_query("What instruments did she play and where did she move?")

    assert '"instrument"*' in expression
    assert '"play"*' in expression
    assert '"move"*' in expression


def test_fts_query_preserves_exact_entity_prefix():
    expression = fts_query("Caroline LGBTQ")

    assert '"caroline"*' in expression
    assert '"lgbtq"*' in expression
