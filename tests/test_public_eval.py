from __future__ import annotations

from scripts.evaluate_retrieval import (
    EvidenceIndex,
    locomo_inputs,
    longmemeval_inputs,
    metrics_for_case,
    timestamp_ms,
)
from tide_mem.config import Settings
from tide_mem.retrieve import RetrievalService
from tide_mem.text import stable_id


def test_message_level_evidence_mapping_credits_raw_windows_and_sourced_cards():
    index = EvidenceIndex(session_level=False)
    index.add_session("request-1", "session-1", ["D1:1", "D1:2", "D1:3"])

    assert index.resolve({"id": stable_id("request-1", "raw", 1)}) == {"D1:2"}
    assert index.resolve({"id": stable_id("request-1", "window", 1, 2)}) == {
        "D1:2",
        "D1:3",
    }
    assert index.resolve(
        {
            "id": "card",
            "content": (
                "[Structured memory evidence | session=session-1 | "
                "source_messages=[2] | event_time=unknown]\nA fact"
            ),
        }
    ) == {"D1:3"}
    assert index.resolve(
        {
            "id": "summary",
            "content": "[Session evidence summary | session=session-1 | source_messages=all]",
        }
    ) == set()


def test_proxy_metrics_do_not_reward_duplicate_records_twice():
    metrics = metrics_for_case(
        [{"A"}, {"A"}, {"B"}],
        {"A", "B"},
        (1, 2, 3),
    )
    assert metrics is not None
    assert metrics["recall_any@1"] == 1.0
    assert metrics["recall_all@2"] == 0.0
    assert metrics["evidence_recall@2"] == 0.5
    assert metrics["recall_all@3"] == 1.0
    assert metrics["mrr"] == 1.0


def test_ablation_settings_validate_and_filter_memory_views(monkeypatch):
    monkeypatch.setenv("TIDE_MEMORY_VIEW", "cards")
    monkeypatch.setenv("TIDE_TEMPORAL_BOOST", "false")
    settings = Settings.from_env()
    service = object.__new__(RetrievalService)
    service.settings = settings

    assert settings.memory_view == "cards"
    assert settings.temporal_boost is False
    assert service._view_allows({"kind": "card_fact"})
    assert service._view_allows({"kind": "session_summary"})
    assert not service._view_allows({"kind": "raw_episode"})


def test_locomo_public_adapter_preserves_speaker_and_evidence_ids():
    conversations = [
        {
            "sample_id": "conv-1",
            "sessions": [
                {
                    "session_index": 1,
                    "date_time": "1:56 pm on 8 May, 2023",
                    "messages": [
                        {
                            "dia_id": "D1:1",
                            "speaker": "Ada",
                            "role": "user",
                            "text": "I moved to Berlin.",
                        }
                    ],
                }
            ],
        }
    ]
    questions = [
        {
            "qa_id": "conv-1#q0000",
            "sample_id": "conv-1",
            "speaker_a": "Ada",
            "speaker_b": "Grace",
            "question": "Where did Ada move?",
            "answer": ["Berlin"],
            "evidence": ["D1:1"],
            "category": "1",
            "is_multi_modality": False,
        }
    ]
    cases, jobs, evidence = locomo_inputs(
        conversations,
        questions,
        namespace="test",
        include_multimodal=False,
        limit=None,
    )

    assert cases[0].gold_evidence == {"D1:1"}
    assert jobs[0].messages[0]["content"] == "Ada: I moved to Berlin."
    assert jobs[0].messages[0]["timestamp"] == 1683554160000
    assert evidence.resolve({"id": stable_id(jobs[0].request_id, "raw", 0)}) == {"D1:1"}


def test_longmemeval_adapter_uses_question_isolation_and_session_labels():
    items = [
        {
            "question_id": "q1",
            "question_type": "knowledge-update",
            "question": "Where does the user live?",
            "answer": "Berlin",
            "haystack_session_ids": ["answer-session"],
            "haystack_dates": ["2025/03/04 (Tue) 10:30"],
            "haystack_sessions": [
                [{"role": "user", "content": "I moved to Berlin.", "has_answer": True}]
            ],
            "answer_session_ids": ["answer-session"],
        }
    ]
    cases, jobs, evidence = longmemeval_inputs(items, namespace="test", limit=None)

    assert cases[0].user_id == "test:longmemeval:q1"
    assert cases[0].gold_evidence == {"answer-session"}
    assert timestamp_ms("2025/03/04 (Tue) 10:30") == 1741084200000
    assert evidence.resolve({"id": stable_id(jobs[0].request_id, "raw", 0)}) == {
        "answer-session"
    }
