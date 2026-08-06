# TIDE-Mem

TIDE-Mem is an initial research prototype for the
[Agent Memory Challenge](https://agentmemories.ai/home), targeting the
**Academic / Textual Memory / GitHub code submission** route.

This repository contains only the reproducible memory service and a local
public-data retrieval proxy. It does not require a challenge Leaderboard Key,
a public deployment, or Render. The challenge platform can build the
Dockerfile and run the Add/Search service inside its evaluator environment.

## Initial method

TIDE-Mem combines four ideas:

1. **Dual-view memory.** Every source message is retained as immutable raw
   evidence, while `gpt-4o-mini` extracts compact semantic memory cards.
2. **Temporal state ledger.** Mutable facts such as locations, preferences,
   and plans are ordered by event/source time so later updates can be preferred
   without deleting historical evidence.
3. **User-isolated hybrid retrieval.** SQLite FTS5, exact entity/time matching,
   recency and state signals are fused with reciprocal-rank fusion. Every read
   and write is scoped by the exact `user_id`.
4. **Evidence-only reranking.** `gpt-4o-mini` plans evidence needs and reranks
   candidate IDs; a coverage-aware selector reduces duplicate results for
   multi-hop, list, and count questions.

Search returns ranked memory evidence, never a final answer. The complete
method is in [docs/METHOD.md](docs/METHOD.md).

## API contract

| Purpose | Endpoint | Default code-submission auth |
|---|---|---|
| Health | `GET /health` | None |
| Add | `POST /v1/memory/add` | None |
| Search | `POST /v1/memory/search` | None |

The optional standalone setting `TIDE_REQUIRE_AUTH=true` enables `X-Api-Key`
authentication using `TIDE_MEMORY_API_KEY`. The Academic code-submission route
does not issue or need that key.

Add is synchronous: all submitted messages are stored and searchable before
HTTP 200 is returned. Repeated `request_id` values are idempotent.

Example Add request:

```json
{
  "request_id": "demo:add:1",
  "messages": [
    {
      "role": "user",
      "timestamp": 1767225600000,
      "content": "I moved from Paris to Berlin in February 2026."
    }
  ],
  "user_id": "demo:user:1",
  "session_id": "demo:session:1"
}
```

Example Search request:

```json
{
  "query": "Where does the user currently live?",
  "user_id": "demo:user:1",
  "top_k": 100
}
```

The Search response is an ordered `data` array containing stable `id`, evidence
`content`, and optional `score` and `created_at`.

## Build and run

Requirements: Docker and, for the full method, secure platform access to the
exact model `gpt-4o-mini`.

```bash
docker build -t tide-mem:0.1.0-amc2026 .
docker run --rm -p 8000:8000 \
  -e TIDE_REQUIRE_AUTH=false \
  -e TIDE_LLM_MODE=heuristic \
  -e TIDE_LLM_REQUIRED=false \
  -e TIDE_DB_PATH=/tmp/tide_mem.sqlite3 \
  tide-mem:0.1.0-amc2026
```

This no-key heuristic mode is for contract checks and public retrieval
experiments. For the submitted full method, the platform should set
`TIDE_LLM_MODE=api`, keep `TIDE_LLM_MODEL=gpt-4o-mini`, and inject
`TIDE_LLM_API_KEY` through its protected runtime environment. Do not put a
provider credential in this repository, commands, issues, or submission notes.

Run a contract smoke test in another terminal:

```bash
python scripts/smoke_test.py --base-url http://127.0.0.1:8000
```

## Local public-data evaluation

The local harness supports the public
[LoCoMo-Refined](https://github.com/mem-eval-suite/LoCoMo_refined) and
[LongMemEval](https://github.com/xiaowu0162/LongMemEval) formats. It calls the
same Add/Search API, measures evidence retrieval, and never needs a challenge
key.

LoCoMo-Refined textual subset:

```bash
git clone https://github.com/mem-eval-suite/LoCoMo_refined.git /tmp/LoCoMo_refined
python scripts/evaluate_retrieval.py locomo \
  --conversations /tmp/LoCoMo_refined/data/public/conversations.jsonl \
  --questions /tmp/LoCoMo_refined/data/public/questions.jsonl \
  --output-dir /tmp/tide-eval/locomo-full \
  --limit 50
```

The default excludes caption-backed multimodal questions because this entry is
for the Textual Memory track. Add `--include-multimodal` only for an explicitly
caption-based experiment.

LongMemEval-S/cleaned:

```bash
python scripts/evaluate_retrieval.py longmemeval \
  --data /path/to/longmemeval_s_cleaned.json \
  --output-dir /tmp/tide-eval/longmemeval-full \
  --limit 20
```

Each run writes:

- `summary.json`: `RecallAny@K`, `RecallAll@K`, evidence recall, NDCG, MRR,
  per-category aggregates, and Add/Search latency;
- `retrieval.jsonl`: question-level ranked evidence and evidence mappings;
- `answer_input.jsonl`: retrieved context for a separate public answer/judge
  pipeline.

Every summary is marked `proxy_public_retrieval` and has
`official_leaderboard_score: null`. These numbers are useful for regression
testing and tuning, but they are **not** official challenge scores. LoCoMo uses
public message-level evidence IDs; LongMemEval uses public session-level
evidence IDs. Questions without public evidence labels are excluded from the
aggregate retrieval score.

## Safe ablations

Use the same public subset, concurrency, `top_k`, and a fresh database for each
variant. The defaults always run the full initial method.

| Variant | Runtime change |
|---|---|
| Full TIDE-Mem | `TIDE_MEMORY_VIEW=full`, `TIDE_TEMPORAL_BOOST=true` |
| Raw evidence only | `TIDE_MEMORY_VIEW=raw` |
| Structured cards only | `TIDE_MEMORY_VIEW=cards` |
| No temporal state boost | `TIDE_TEMPORAL_BOOST=false` |
| No LLM evidence rerank | `TIDE_RERANK_CANDIDATE_LIMIT=0` |
| Fully local smoke baseline | `TIDE_LLM_MODE=heuristic` |

Change the evaluation `--namespace` and `TIDE_DB_PATH` between variants so no
previous memories carry over. Tune only on public data; do not infer private
labels, hard-code benchmark answers, or share state across `user_id` values.

## Academic code submission

On the challenge submission form choose:

- Leaderboard: **Academic leaderboard**
- Method: **Submit GitHub code for platform deployment**
- System name: **TIDE-Mem**
- Version name: **v0.1.0-amc2026**
- Public repository: `https://github.com/xiye7lai/TIDE-Mem`

Suggested run notes:

> Build the repository root with Dockerfile and expose container port 8000.
> Health: GET /health. Add: POST /v1/memory/add. Search: POST
> /v1/memory/search. Set TIDE_REQUIRE_AUTH=false, TIDE_LLM_MODE=api,
> TIDE_LLM_MODEL=gpt-4o-mini, and inject the model-provider credential only
> through the protected runtime environment. Use one container worker because
> SQLite is the persistent memory store. Search top_k supports 100.

The form does not need a Leaderboard Key, Memory System Key, public HTTPS URL,
or 30-day hosted service for this route. Pin the submitted source to a commit
SHA so the evaluated code remains reproducible.

## Configuration

| Variable | Default or purpose |
|---|---|
| `TIDE_LLM_API_KEY` | Protected provider credential for full API mode |
| `TIDE_LLM_MODEL` | `gpt-4o-mini` |
| `TIDE_LLM_REASONING_EFFORT` | Empty for the submitted model; optional compatibility knob for local alternate-model experiments |
| `TIDE_REQUIRE_AUTH` | `false` for platform code submission |
| `TIDE_DB_PATH` | `/data/tide_mem.sqlite3` |
| `TIDE_TTL_DAYS` | `30` |
| `TIDE_LLM_MAX_CONCURRENCY` | `16` |
| `TIDE_MEMORY_VIEW` | `full`, with `raw` and `cards` for ablations |
| `TIDE_TEMPORAL_BOOST` | `true` |
| `TIDE_RERANK_CANDIDATE_LIMIT` | `20`; use `0` for an ablation |

See [.env.example](.env.example) for the remaining bounded settings.
See [docs/PUBLIC_EVALUATION.md](docs/PUBLIC_EVALUATION.md) for the reproducible
public proxy experiment and its limitations.

## Validation

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=. pytest -q
python -m compileall -q tide_mem scripts
bash -n deploy/docker-entrypoint.sh
docker build -t tide-mem:0.1.0-amc2026 .
```

The tests cover synchronous Add/Search behavior, optional authentication,
exact `user_id` isolation, idempotency, `top_k`, temporal updates, the mocked
API-mode chain, public dataset adapters, and proxy retrieval metrics.

## Data handling

Request bodies and retrieved evidence are not written to application logs.
Stored data expires after 30 days by default. No private benchmark examples,
labels, provider credentials, or hard-coded answers are included.

## License

MIT.
