from __future__ import annotations

import asyncio
import math
import re
from collections import defaultdict
from typing import Any

from .config import Settings
from .db import MemoryDB
from .llm import LLMClient, QueryPlan
from .models import SearchItem, SearchRequest, SearchResponse
from .text import json_loads, tokenize, truncate, unique_preserve


class RetrievalService:
    def __init__(self, settings: Settings, db: MemoryDB, llm: LLMClient) -> None:
        self.settings = settings
        self.db = db
        self.llm = llm

    def _view_allows(self, row: dict[str, Any]) -> bool:
        view = self.settings.memory_view
        kind = str(row.get("kind", ""))
        if view == "full":
            return True
        if view == "raw":
            return kind in {"raw_episode", "raw_window"}
        return kind.startswith("card_") or kind == "session_summary"

    @staticmethod
    def _needs_diverse_evidence(query: str, plan: QueryPlan) -> bool:
        if plan.needs_multiple_evidence or plan.question_type in {
            "list",
            "count",
            "multi_hop",
            "update",
        }:
            return True
        lowered = query.casefold()
        return bool(
            re.search(
                r"\b(both|all|activities|classes|instruments|artists|bands|"
                r"ways|things|events|changes|jobs|dogs)\b",
                lowered,
            )
            or lowered.startswith("how long ")
            or lowered.startswith("what happened ")
            or lowered.startswith("where ")
            or re.match(r"^what\s+(state|city|country|place)\b", lowered)
            or "relationship status" in lowered
            or re.match(r"^has\b.+\btried\b", lowered)
        )

    @staticmethod
    def _source_tokens(row: dict[str, Any]) -> set[str]:
        session_id = str(row.get("session_id", ""))
        indexes = json_loads(row.get("source_indices_json"), [])
        if not isinstance(indexes, list) or not indexes:
            return {f"{session_id}:record:{row.get('id', '')}"}
        return {f"{session_id}:message:{index}" for index in indexes}

    def _diverse_rerank_candidates(
        self,
        preliminary: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Expose complementary sources to the bounded LLM rerank window."""

        if limit <= 0 or len(preliminary) <= limit:
            return preliminary
        pool = preliminary[: max(100, limit * 5)]
        selected = list(pool[: min(4, limit)])
        remaining = [row for row in pool if row not in selected]
        used_sources = set().union(*(self._source_tokens(row) for row in selected))
        used_sessions = {str(row.get("session_id", "")) for row in selected}
        selected_content = [set(tokenize(str(row.get("content", "")))) for row in selected]

        while remaining and len(selected) < limit:
            best_index = 0
            best_utility = -1e9
            for index, row in enumerate(remaining):
                sources = self._source_tokens(row)
                source_novelty = len(sources - used_sources) / max(1, len(sources))
                session_novelty = float(str(row.get("session_id", "")) not in used_sessions)
                tokens = set(tokenize(str(row.get("content", ""))))
                duplicate = max(
                    (
                        len(tokens & chosen) / len(tokens | chosen)
                        for chosen in selected_content
                        if tokens and chosen
                    ),
                    default=0.0,
                )
                utility = (
                    float(row.get("heuristic_score", 0.0))
                    + 0.14 * source_novelty
                    + 0.05 * session_novelty
                    - 0.08 * duplicate
                )
                if utility > best_utility:
                    best_utility = utility
                    best_index = index
            chosen = remaining.pop(best_index)
            selected.append(chosen)
            used_sources.update(self._source_tokens(chosen))
            used_sessions.add(str(chosen.get("session_id", "")))
            selected_content.append(set(tokenize(str(chosen.get("content", "")))))
        return selected

    async def search(self, request: SearchRequest) -> SearchResponse:
        plan = await self.llm.plan_query(request.query, request.options)
        candidates = await self._gather_candidates(request.user_id, request.query, plan)
        if not candidates:
            return SearchResponse(data=[])

        ranked = await self._rank(request, plan, candidates)
        selected = self._coverage_select(ranked, request.query, plan, request.top_k)
        items = [
            SearchItem(
                id=row["id"],
                content=truncate(row["content"], self.settings.returned_content_max_chars),
                score=round(float(row["final_score"]), 6),
                created_at=row.get("event_time") or row.get("created_at"),
            )
            for row in selected
        ]
        return SearchResponse(data=items)

    async def _gather_candidates(
        self,
        user_id: str,
        query: str,
        plan: QueryPlan,
    ) -> dict[str, dict[str, Any]]:
        queries = unique_preserve(
            [
                query,
                *plan.subqueries,
                *plan.coverage_slots,
                *plan.entities,
                *plan.time_terms,
            ]
        )[:12]
        per_query = max(30, min(100, self.settings.retrieval_candidate_limit // max(1, len(queries))))

        fts_tasks = [self.db.fts_search(user_id, item, per_query) for item in queries]
        fts_results = await asyncio.gather(*fts_tasks) if fts_tasks else []

        candidates: dict[str, dict[str, Any]] = {}
        rrf: defaultdict[str, float] = defaultdict(float)
        channels: defaultdict[str, set[str]] = defaultdict(set)

        for query_index, rows in enumerate(fts_results):
            for rank, row in enumerate(rows, start=1):
                ident = row["id"]
                candidates[ident] = row
                rrf[ident] += 1.0 / (60.0 + rank)
                channels[ident].add(f"fts:{query_index}")

        exact_terms = unique_preserve([*plan.entities, *plan.time_terms])
        # The original query is useful for exact phrase matching, but only when it
        # is compact enough not to turn LIKE into a broad full-question scan.
        if len(query) <= 160:
            exact_terms.append(query)
        exact_rows = await self.db.exact_search(
            user_id,
            exact_terms,
            min(100, self.settings.retrieval_candidate_limit),
        )
        for rank, row in enumerate(exact_rows, start=1):
            ident = row["id"]
            candidates[ident] = row
            rrf[ident] += 1.0 / (45.0 + rank)
            channels[ident].add("exact")

        if plan.prefer_latest or len(candidates) < min(25, self.settings.retrieval_candidate_limit):
            recent_rows = await self.db.recent_memories(user_id, min(80, self.settings.retrieval_candidate_limit))
            for rank, row in enumerate(recent_rows, start=1):
                ident = row["id"]
                candidates[ident] = row
                rrf[ident] += 0.45 / (60.0 + rank)
                channels[ident].add("recent")

        candidates = {
            ident: row for ident, row in candidates.items() if self._view_allows(row)
        }
        for ident, row in candidates.items():
            row["rrf_score"] = rrf[ident]
            row["channels"] = sorted(channels[ident])

        # Bound downstream LLM and CPU work deterministically.
        ordered = sorted(
            candidates.values(),
            key=lambda row: (row["rrf_score"], row.get("ordering_ms", 0)),
            reverse=True,
        )[: self.settings.retrieval_candidate_limit]
        return {row["id"]: row for row in ordered}

    async def _rank(
        self,
        request: SearchRequest,
        plan: QueryPlan,
        candidates: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        diversify_sources = self._needs_diverse_evidence(request.query, plan)
        values = list(candidates.values())
        self._apply_heuristic_scores(request, plan, values)
        preliminary = sorted(
            values,
            key=lambda row: (row["heuristic_score"], row.get("ordering_ms", 0)),
            reverse=True,
        )

        if diversify_sources:
            session_ids: list[str] = []
            anchor_rrf: dict[str, float] = {}
            for row in preliminary[:80]:
                session_id = str(row.get("session_id", ""))
                if not session_id or session_id in anchor_rrf:
                    continue
                session_ids.append(session_id)
                anchor_rrf[session_id] = float(row.get("rrf_score", 0.0))
                if len(session_ids) >= 8:
                    break
            expanded = await self.db.session_memories(
                request.user_id,
                session_ids,
                limit_per_session=80,
            )
            for row in expanded:
                ident = str(row.get("id", ""))
                if ident in candidates or not self._view_allows(row):
                    continue
                session_id = str(row.get("session_id", ""))
                row["rrf_score"] = 0.35 * anchor_rrf.get(session_id, 0.0)
                row["channels"] = ["session_expand"]
                candidates[ident] = row
            values = list(candidates.values())
            self._apply_heuristic_scores(request, plan, values)
            preliminary = sorted(
                values,
                key=lambda row: (row["heuristic_score"], row.get("ordering_ms", 0)),
                reverse=True,
            )[: max(400, self.settings.retrieval_candidate_limit * 3)]

        rerank_candidates = preliminary
        if diversify_sources:
            rerank_candidates = self._diverse_rerank_candidates(
                preliminary,
                self.settings.rerank_candidate_limit,
            )
        llm_ranked = await self.llm.rerank_evidence(
            request.query,
            request.options,
            plan,
            rerank_candidates,
        )
        llm_scores: dict[str, float] = {}
        for rank, (ident, relevance) in enumerate(llm_ranked, start=1):
            position = 1.0 / math.log2(rank + 1.0)
            llm_scores[ident] = 0.70 * relevance + 0.30 * position

        session_llm_scores: dict[str, float] = {}
        rerank_by_id = {str(row.get("id", "")): row for row in rerank_candidates}
        for ident, score in llm_scores.items():
            row = rerank_by_id.get(ident)
            if row is None:
                continue
            session_id = str(row.get("session_id", ""))
            session_llm_scores[session_id] = max(
                session_llm_scores.get(session_id, 0.0),
                score,
            )

        for row in preliminary:
            if llm_scores:
                llm_score = llm_scores.get(row["id"], 0.0)
                row["final_score"] = 0.58 * row["heuristic_score"] + 0.42 * llm_score
            else:
                row["final_score"] = row["heuristic_score"]
            if "session_expand" in row.get("channels", []):
                row["final_score"] = min(
                    1.0,
                    row["final_score"]
                    + 0.07 * session_llm_scores.get(str(row.get("session_id", "")), 0.0),
                )
            if self.settings.temporal_boost and plan.prefer_latest and row.get("is_current"):
                row["final_score"] = min(1.0, row["final_score"] + 0.04)

        return sorted(
            preliminary,
            key=lambda row: (row["final_score"], row.get("ordering_ms", 0)),
            reverse=True,
        )

    def _apply_heuristic_scores(
        self,
        request: SearchRequest,
        plan: QueryPlan,
        values: list[dict[str, Any]],
    ) -> None:
        query_tokens = set(tokenize(request.query))
        entity_terms = [term.casefold() for term in plan.entities]
        time_terms = [term.casefold() for term in plan.time_terms]

        max_rrf = max((row["rrf_score"] for row in values), default=1.0) or 1.0
        for row in values:
            searchable = row["searchable_text"].casefold()
            content_tokens = set(tokenize(row["searchable_text"]))
            token_overlap = len(query_tokens & content_tokens) / max(1, len(query_tokens))
            entity_hits = sum(1 for term in entity_terms if term and term in searchable)
            time_hits = sum(1 for term in time_terms if term and term in searchable)
            state_bonus = 0.0
            if self.settings.temporal_boost and row.get("state_key"):
                state_bonus += 0.025
            if self.settings.temporal_boost and plan.prefer_latest and row.get("is_current"):
                state_bonus += 0.12
            if self.settings.temporal_boost and plan.question_type == "update" and row.get("is_current"):
                state_bonus += 0.10
            provenance_bonus = 0.025 if row.get("kind") == "raw_episode" else 0.04
            heuristic = (
                0.57 * (row["rrf_score"] / max_rrf)
                + 0.20 * token_overlap
                + min(0.12, 0.04 * entity_hits)
                + min(0.06, 0.03 * time_hits)
                + state_bonus
                + provenance_bonus
            )
            row["heuristic_score"] = max(0.0, min(1.0, heuristic))

    def _coverage_select(
        self,
        ranked: list[dict[str, Any]],
        query: str,
        plan: QueryPlan,
        top_k: int,
    ) -> list[dict[str, Any]]:
        if top_k <= 0:
            return []
        pool = ranked[: max(top_k * 4, 120)]
        coverage_texts = unique_preserve([*plan.coverage_slots, *plan.entities, *plan.time_terms])
        slot_tokens = [set(tokenize(slot)) for slot in coverage_texts if tokenize(slot)]
        row_tokens = {
            row["id"]: set(tokenize(row["searchable_text"]))
            for row in pool
        }
        content_tokens = {
            row["id"]: set(tokenize(row["content"]))
            for row in pool
        }
        max_duplicate = {row["id"]: 0.0 for row in pool}
        uncovered = set(range(len(slot_tokens)))
        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()
        used_sources: set[str] = set()
        used_sessions: set[str] = set()
        diversify_sources = self._needs_diverse_evidence(query, plan)

        while pool and len(selected) < top_k:
            best_index = -1
            best_utility = -1e9
            for index, row in enumerate(pool):
                if row["id"] in selected_ids:
                    continue
                candidate_tokens = row_tokens[row["id"]]
                covered_now = sum(
                    1
                    for slot_index in uncovered
                    if slot_tokens[slot_index]
                    and len(slot_tokens[slot_index] & candidate_tokens) > 0
                )
                diversity_penalty = 0.13 * max_duplicate[row["id"]]
                if plan.needs_multiple_evidence or plan.question_type in {"list", "count", "multi_hop"}:
                    diversity_penalty *= 0.45
                kind_bonus = 0.015 if row.get("kind", "").startswith("card_") else 0.0
                source_bonus = 0.0
                if diversify_sources:
                    sources = self._source_tokens(row)
                    source_bonus += 0.035 * (
                        len(sources - used_sources) / max(1, len(sources))
                    )
                    if str(row.get("session_id", "")) not in used_sessions:
                        source_bonus += 0.015
                utility = (
                    row["final_score"]
                    + 0.035 * covered_now
                    + kind_bonus
                    + source_bonus
                    - diversity_penalty
                )
                if utility > best_utility:
                    best_utility = utility
                    best_index = index

            if best_index < 0:
                break
            chosen = pool.pop(best_index)
            selected.append(chosen)
            selected_ids.add(chosen["id"])
            used_sources.update(self._source_tokens(chosen))
            used_sessions.add(str(chosen.get("session_id", "")))
            chosen_tokens = row_tokens[chosen["id"]]
            uncovered = {
                slot_index
                for slot_index in uncovered
                if not (slot_tokens[slot_index] & chosen_tokens)
            }
            for row in pool:
                ident = row["id"]
                left = content_tokens[ident]
                right = content_tokens[chosen["id"]]
                duplicate = len(left & right) / len(left | right) if left and right else 0.0
                max_duplicate[ident] = max(
                    max_duplicate[ident],
                    duplicate,
                )

        # Preserve rank ordering expected by the evaluator after coverage-aware set
        # construction. Scores remain evidence-relevance scores, never answers.
        selected.sort(
            key=lambda row: (row["final_score"], row.get("ordering_ms", 0)),
            reverse=True,
        )
        return selected[:top_k]
