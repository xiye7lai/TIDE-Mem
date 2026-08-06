from __future__ import annotations

from tide_mem.llm import QueryPlan
from tide_mem.retrieve import RetrievalService


def _plan(**overrides):
    values = {
        "question_type": "fact",
        "subqueries": [],
        "entities": [],
        "time_terms": [],
        "coverage_slots": [],
        "prefer_latest": False,
        "needs_multiple_evidence": False,
    }
    values.update(overrides)
    return QueryPlan(**values)


def test_plural_and_elapsed_queries_force_diverse_evidence():
    assert RetrievalService._needs_diverse_evidence(
        "What writing classes has Maria taken?", _plan()
    )
    assert RetrievalService._needs_diverse_evidence(
        "How long did it take to open the studio?", _plan(question_type="temporal")
    )
    assert RetrievalService._needs_diverse_evidence(
        "What state did Nate visit?", _plan()
    )
    assert not RetrievalService._needs_diverse_evidence(
        "Who owns the studio?", _plan()
    )


def test_diverse_rerank_pool_includes_complementary_sources():
    service = object.__new__(RetrievalService)
    rows = []
    for index in range(8):
        rows.append(
            {
                "id": f"duplicate-{index}",
                "session_id": "session-a",
                "source_indices_json": "[1]",
                "content": "the same highly ranked evidence",
                "heuristic_score": 1.0 - index * 0.01,
            }
        )
    rows.append(
        {
            "id": "complementary",
            "session_id": "session-b",
            "source_indices_json": "[7]",
            "content": "different supporting evidence",
            "heuristic_score": 0.88,
        }
    )

    selected = service._diverse_rerank_candidates(rows, limit=5)

    assert len(selected) == 5
    assert any(row["id"] == "complementary" for row in selected)
