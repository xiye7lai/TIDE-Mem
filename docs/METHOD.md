# TIDE-Mem method

## 1. Problem formulation

For each identity boundary `u = user_id`, the system receives a sequence of Add requests containing source conversations and later a Search request containing a question `q`, optional choices `o`, and return budget `K`. The system must produce a ranked evidence set

```text
E_K(u, q, o) = [e_1, ..., e_m],  m <= K,
```

without generating the final answer. Evidence from any `u' != u` is inadmissible.

TIDE-Mem is built around three failure modes common in long-memory retrieval:

1. **lossy consolidation**: a summary drops an exact name, date, negation, or provenance;
2. **stale-state dominance**: an older preference/location/plan outranks a later correction;
3. **single-snippet myopia**: several individually relevant records are returned, but they all cover the same part of a multi-hop or list question.

## 2. Dual-view memory writing

Every Add request creates two complementary views.

### 2.1 Immutable episodic view

Each original message is persisted verbatim with:

- stable ID derived from request and source index;
- exact `user_id` and `session_id`;
- role, source message index, optional source timestamp;
- raw content and lexical search text.

Overlapping two-message windows additionally preserve local adjacency for pronouns, replies, and corrections. This is the provenance anchor: a semantic extraction mistake cannot erase the original evidence.

### 2.2 Structured semantic view

`gpt-4o-mini` receives the source chunk as untrusted data and emits JSON memory cards. A card contains:

```text
(kind, content, entities, keywords, event_time,
 state_key, change_type, source_message_indexes)
```

The extraction instruction requires self-contained evidence and preserves names, dates, places, titles, quantities, preferences, rules, plans, changes, and negations. The source text is retained separately; no card is treated as an answer.

A short evidence-focused session summary is also stored for broad recall. The maximum number of cards and summaries per Add is bounded by configuration.

## 3. Temporal state ledger

Mutable facts may be linked by a normalized `state_key`. Before extracting a new Add chunk, TIDE-Mem supplies the same user's bounded current-state key list as untrusted naming hints, allowing `gpt-4o-mini` to reuse keys across requests without treating prior content as new source evidence. Example keys include:

```text
profile.home_city
preference.favorite_restaurant
plan.conference_trip
```

Supported update operations are `set`, `append`, `cancel`, `complete`, and `none`. For state-changing operations, current status is recomputed transactionally:

```text
current(u, k) = argmax_e ordering_time(e)
               subject to e.user_id = u and e.state_key = k.
```

`ordering_time` prefers an explicitly extracted event time, then a source message timestamp, then local persistence time. This avoids treating concurrent request arrival order as ground truth. Superseded evidence remains retrievable for questions about history or conflict.

## 4. Storage and identity isolation

The implementation uses SQLite in WAL mode plus FTS5. The relevant invariant is:

```text
Every read and write is keyed by exact user_id.
```

Search never uses `session_id` as a replacement for `user_id`, never falls back to a global index, and never shares caches across users. SQL parameters prevent query-string interpolation.

Add is idempotent on `request_id`. A transaction inserts the request, all memory records, FTS rows, and state updates before success is returned.

## 5. Evidence-only retrieval

### 5.1 Query planning

`gpt-4o-mini` maps the untrusted question and optional choices to an evidence plan:

```text
(question_type, subqueries, entities, time_terms,
 coverage_slots, prefer_latest, needs_multiple_evidence)
```

The planner is prohibited from returning an answer or option label. Its output describes what should be found, not what the answer is.

### 5.2 Candidate generation

Candidates are gathered through independent, user-scoped channels:

- FTS5 BM25 over the original query;
- FTS5 over decomposed subqueries;
- exact entity and time-term substring matches;
- bounded recent/current-state fallback for temporal questions.

For a candidate `e` found at rank `r_c(e)` in channel `c`, reciprocal-rank fusion uses

```text
RRF(e) = sum_c 1 / (60 + r_c(e)).
```

Exact matching uses a slightly stronger denominator to preserve names and dates.

### 5.3 Deterministic evidence score

The initial score combines normalized RRF, token overlap, entity/time hits, state relevance, and provenance-kind priors:

```text
S_h(e) = 0.57 RRF_norm
       + 0.20 token_overlap
       + entity_bonus
       + time_bonus
       + state_bonus
       + provenance_bonus.
```

For questions that explicitly request the latest/current state, a current ledger member receives a boost, while older records remain candidates.

### 5.4 Evidence-ID reranking

At most a bounded number of candidates is sent to `gpt-4o-mini`. The model sees IDs and short evidence snippets, treats all text as untrusted, and returns only:

```json
{"ranked": [{"id": "candidate-id", "score": 0.0}]}
```

It cannot create final evidence text or answer the question. Unknown or duplicate IDs are discarded programmatically. The final relevance score combines deterministic and LLM ranking signals.

### 5.5 Coverage-aware selection

A greedy selector rewards candidates that cover still-unmet plan slots and penalizes high Jaccard duplication. The duplicate penalty is reduced for list, count, and multi-hop questions, where several records are expected.

For candidate `e` at a selection step:

```text
utility(e) = final_score(e)
           + coverage_bonus(e)
           + structured_card_bonus(e)
           - duplicate_penalty(e, selected).
```

After set construction, records are returned in descending relevance-score order, never exceeding `top_k`.

## 6. Safety and compliance properties

- **No final answer generation:** Search LLM outputs plans or evidence IDs only.
- **No cross-user retrieval:** all database candidate channels contain `WHERE user_id = ?`.
- **No benchmark hard-coding:** the repository contains synthetic examples only.
- **Prompt-injection resistance:** conversations, questions, choices, and candidates are marked untrusted in system instructions; structured output is validated.
- **Immediate consistency:** Add commits database and FTS rows before HTTP 200.
- **Traceability:** every returned record includes stable ID and source/persistence time.
- **Minimal logging:** request bodies and evidence are not logged.
- **Retention:** background and startup cleanup enforce a configurable 30-day TTL.

## 7. Complexity

Let `N_u` be records for one user, `Q` the number of query expansions, `C` the fused candidate bound, and `R` the LLM-rerank bound.

- Add database work is linear in source messages plus extracted cards.
- FTS candidate retrieval is approximately `Q * O(log N_u + hits)` under the index.
- deterministic ranking is `O(C)`;
- the bounded reranker processes at most `R` snippets;
- greedy coverage selection is `O(KC)` in the current simple implementation, with small fixed `C` and `K <= 100`.

## 8. Reproducibility knobs

The evaluated tag should fix:

- model: `gpt-4o-mini`;
- temperature: 0;
- extraction/rerank prompts in `tide_mem/llm.py`;
- card/summary/candidate bounds in `.env`;
- memory-view and temporal-boost settings (the evaluated defaults are
  `TIDE_MEMORY_VIEW=full` and `TIDE_TEMPORAL_BOOST=true`);
- dependency versions in `requirements.txt`;
- database schema and ranking weights in source;
- Git commit and Docker image digest.

## 9. Public local ablations

The public proxy in `scripts/evaluate_retrieval.py` can compare:

1. raw episodic evidence only;
2. structured cards only;
3. dual view without temporal state boosts;
4. dual view without evidence planner/reranker;
5. full TIDE-Mem.

It reports public-evidence retrieval metrics and latency percentiles. These are
local proxy results, not official leaderboard scores. Do not tune on private
questions, infer private labels, or carry memory across evaluation identities.
