# TIDE-Mem

TIDE-Mem is an initial research prototype for the
[Agent Memory Challenge](https://agentmemories.ai/home), targeting the
**Academic / Textual Memory / self-hosted Add/Search API** route.

It implements only the memory service required by the competition:

- `GET /health`
- `POST /v1/memory/add`
- `POST /v1/memory/search`

Search returns ranked memory evidence, not a final answer.

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

The complete method description is in [docs/METHOD.md](docs/METHOD.md).

## API contract

| Purpose | Endpoint | Authentication |
|---|---|---|
| Health | `GET /health` | None |
| Add | `POST /v1/memory/add` | `X-Api-Key` |
| Search | `POST /v1/memory/search` | `X-Api-Key` |

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

The Search response is an ordered `data` array whose items contain stable
`id`, evidence `content`, and optional `score` and `created_at`.

## Local Docker run

Requirements: Docker and access to the exact model `gpt-4o-mini`.

```bash
cp .env.example .env
# Set TIDE_MEMORY_API_KEY and TIDE_LLM_API_KEY only in .env.
docker compose up --build -d
curl -fsS http://127.0.0.1:8000/health
```

Run the contract smoke test:

```bash
export TIDE_MEMORY_API_KEY='<the same local memory-system key>'
python scripts/smoke_test.py --base-url http://127.0.0.1:8000
```

Do not commit `.env` or place either key in commands, issues, screenshots, or
public documentation.

## Minimal public deployment

The included [render.yaml](render.yaml) creates one Docker web service with a
persistent SQLite disk, public HTTPS, a generated Memory System Key, and
`gpt-4o-mini` configuration.

Open:

```text
https://render.com/deploy?repo=https://github.com/xiye7lai/TIDE-Mem
```

On Render:

1. review the Starter service and 1 GB persistent disk;
2. enter `TIDE_LLM_API_KEY` only in Render's protected environment field;
3. create the Blueprint and wait for `/health` to become healthy;
4. copy the generated `TIDE_MEMORY_API_KEY` from Render's protected
   Environment page;
5. run `scripts/smoke_test.py` locally before requesting evaluation access.

## Request the competition Evaluation Key

On the challenge's **Submit Evaluation Request** form select:

- Leaderboard: **Academic leaderboard**
- Method: **Provide Add/Search APIs**
- System name: **TIDE-Mem**
- Version name: **v0.1.0-amc2026**
- Add API URL: `https://<service>.onrender.com/v1/memory/add`
- Search API URL: `https://<service>.onrender.com/v1/memory/search`
- Authentication: **X-Api-Key**
- Project URL: `https://github.com/xiye7lai/TIDE-Mem`

Enter the generated Memory System Key only in the form's protected key field.
The service must remain publicly reachable and stable for at least 30 days.

Suggested submission note:

> TIDE-Mem v0.1.0-amc2026 is a synchronous FastAPI Add/Search memory service.
> It uses immutable raw evidence plus gpt-4o-mini semantic cards, a temporal
> state ledger, exact user_id isolation, SQLite FTS5 hybrid retrieval,
> evidence-only reranking, and coverage-aware selection. Docker entrypoint:
> Dockerfile. Add and Search concurrency: 16. Maximum top_k: 100. Evaluation
> data is not logged and is deleted within 30 days.

## Configuration

| Variable | Required value or purpose |
|---|---|
| `TIDE_MEMORY_API_KEY` | Private key used by the evaluator |
| `TIDE_LLM_API_KEY` | Private model-provider key |
| `TIDE_LLM_MODEL` | `gpt-4o-mini` |
| `TIDE_DB_PATH` | Persistent SQLite path |
| `TIDE_LLM_MAX_CONCURRENCY` | Default `16` |
| `TIDE_TTL_DAYS` | Default `30` |

See [.env.example](.env.example) for the remaining bounded retrieval settings.

## Validation

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=. pytest -q
python -m compileall -q tide_mem scripts
bash -n deploy/docker-entrypoint.sh
docker build -t tide-mem:0.1.0-amc2026 .
```

The tests cover synchronous Add/Search behavior, authentication, exact
`user_id` isolation, idempotency, `top_k`, temporal updates, and the full
mocked API-mode chain.

## Data handling

Evaluation content is used only for evaluation. Request bodies and retrieved
evidence are not written to application logs. Stored data expires after 30
days by default. No benchmark labels, private evaluation examples, or
hard-coded answers are included.

## License

MIT.
