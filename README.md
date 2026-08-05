# TIDE-Mem

**Temporal, Identity-Isolated, Dual-view Evidence Memory** — an open-source Add/Search memory service prepared for the **Agent Memory Challenge 2026, Academic Methods / Textual Memory / self-hosted API route**.

> Status: reproducible initial submission candidate (`v0.1.0-amc2026`). It has passed the repository's local contract and isolation tests, but no official leaderboard score is claimed yet.

中文参赛操作入口：[`START_HERE_中文.md`](START_HERE_中文.md)。规则逐条核对见 [`docs/RULES_AND_DECISION.md`](docs/RULES_AND_DECISION.md)，已执行的验证见 [`docs/VALIDATION.md`](docs/VALIDATION.md)。

## Why TIDE-Mem

Many memory baselines either return raw lexical matches or replace the source with lossy summaries. TIDE-Mem keeps both:

1. **Immutable episodic evidence**: every source message is stored verbatim with session, message index, role, and source time; overlapping two-message windows preserve local dialogue adjacency.
2. **Structured semantic cards**: `gpt-4o-mini` extracts self-contained facts, events, preferences, rules, plans, relationships, and mutable-state updates.
3. **Temporal state ledger**: cards may carry a stable `state_key`, event time, and update operation. Same-user current keys are supplied as bounded naming hints across Add calls, and current state is recomputed from source/event time rather than request arrival order.
4. **Evidence-planned retrieval**: `gpt-4o-mini` decomposes a question into evidence needs without answering it. SQLite FTS5, exact entity/time matching, recency/state signals, reciprocal-rank fusion, and an evidence-only LLM reranker are combined.
5. **Coverage-aware output**: multi-hop, list, and count questions favor complementary evidence instead of near-duplicate snippets.
6. **Hard identity boundary**: every database query is scoped by the exact `user_id`; `session_id` is provenance only and never broadens retrieval.

TIDE-Mem's `Search` endpoint returns memory evidence only. Final answer generation remains the evaluation platform's responsibility.

## Architecture

```text
Add(messages, user_id, session_id)
        │
        ├── immutable raw evidence ───────────────┐
        ├── gpt-4o-mini semantic extraction      │
        └── temporal state reconciliation        │
                                                  ▼
                                      SQLite + FTS5 (user scoped)
                                                  │
Search(query, options, user_id, top_k)             │
        │                                         │
        ├── gpt-4o-mini evidence plan             │
        ├── FTS / exact / temporal candidate retrieval
        ├── reciprocal-rank fusion + state boosts│
        ├── gpt-4o-mini evidence-ID reranking     │
        └── coverage/diversity selection ─────────┘
                         │
                         ▼
              {"data": [{"id", "content", ...}]}
```

More detail is in [`docs/METHOD.md`](docs/METHOD.md).

## Competition API contract

| Purpose | Method and path | Authentication |
|---|---|---|
| Health | `GET /health` | none |
| Add | `POST /v1/memory/add` | `X-Api-Key`, `Bearer`, or `Token` |
| Search | `POST /v1/memory/search` | same Memory System Key |

### Add example

```bash
curl -sS -X POST "$BASE_URL/v1/memory/add" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: $TIDE_MEMORY_API_KEY" \
  -d '{
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
  }'
```

Successful response:

```json
{
  "success": true,
  "request_id": "demo:add:1",
  "user_id": "demo:user:1",
  "session_id": "demo:session:1"
}
```

The transaction is committed and its evidence is searchable before HTTP 200 is returned. Replaying an existing `request_id` is idempotent.

### Search example

```bash
curl -sS -X POST "$BASE_URL/v1/memory/search" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TIDE_MEMORY_API_KEY" \
  -d '{
    "query": "Where does the user currently live?",
    "user_id": "demo:user:1",
    "top_k": 100
  }'
```

The response is a JSON object containing a ranked `data` array. Every item has a stable non-empty `id` and evidence-only `content`; `score` and `created_at` are included as permitted optional fields.

## Fastest reproducible start: Docker Compose

Requirements: Docker with Compose, an OpenAI-compatible Chat Completions endpoint that serves the exact model name `gpt-4o-mini`, and two distinct secrets.

```bash
cp .env.example .env
# Edit .env: set TIDE_MEMORY_API_KEY and TIDE_LLM_API_KEY.
docker compose up --build -d
python scripts/smoke_test.py \
  --base-url http://127.0.0.1:8000 \
  --memory-key "$(grep '^TIDE_MEMORY_API_KEY=' .env | cut -d= -f2-)"
```

Inspect health without authentication:

```bash
curl -fsS http://127.0.0.1:8000/health
```

Stop without deleting the persistent database:

```bash
docker compose down
```

## Fastest public deployment: Render Blueprint

The repository includes [`render.yaml`](render.yaml) for a single paid Docker
web service in Frankfurt with a 1 GB persistent disk, public HTTPS, HTTP health
checks, disabled automatic redeploys, and a generated Memory System Key. The
only secret you enter during Blueprint creation is the provider key used for
`gpt-4o-mini`.

After publishing the repository to GitHub, open:

```text
https://render.com/deploy?repo=https://github.com/<OWNER>/<REPOSITORY>
```

Review the paid resources, enter `TIDE_LLM_API_KEY`, and approve the Blueprint.
Then retrieve the generated `TIDE_MEMORY_API_KEY` from the Render environment
settings and verify the endpoint without placing the key on the command line:

```powershell
.\scripts\verify_hosted.ps1 -BaseUrl https://<service>.onrender.com
```

On Windows, double-click [`PUBLISH_TO_GITHUB.cmd`](PUBLISH_TO_GITHUB.cmd),
or run:

```powershell
.\scripts\publish_github.ps1
```

The publication script creates an isolated `.venv`, runs the repository checks,
installs missing Git, Python 3.11, or GitHub CLI prerequisites with `winget`,
and uses GitHub's browser authorization flow. It does not accept a password or
token. It then re-attributes the frozen commit, recreates the annotated tag,
creates a new public repository, pushes
`main` and the tag, creates a Release, starts CI and the tagged GHCR image
build, records non-secret metadata under ignored `submission-private/`, and
opens the repository-specific Render deployment page.

If `tide-mem` already exists in the authenticated account, choose a new empty
name instead of overwriting it:

```powershell
.\scripts\publish_github.ps1 -RepoName tide-mem-amc2026
```

## Direct Python run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

export TIDE_MEMORY_API_KEY='replace-with-a-long-random-key'
export TIDE_LLM_API_KEY='replace-with-your-provider-key'
export TIDE_DB_PATH="$PWD/data/tide_mem.sqlite3"

uvicorn tide_mem.api:app --host 0.0.0.0 --port 8000
```

For local tests only, deterministic heuristic mode avoids external LLM calls:

```bash
export TIDE_LLM_MODE=heuristic
export TIDE_LLM_REQUIRED=false
export TIDE_MEMORY_API_KEY=test-key
export TIDE_DB_PATH="$PWD/data/test.sqlite3"
uvicorn tide_mem.api:app --host 127.0.0.1 --port 8000
```

Do **not** use heuristic mode for the formal challenge version.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `TIDE_MEMORY_API_KEY` | none | Participant-issued key used by the evaluator to call Add/Search |
| `TIDE_LLM_API_KEY` | `OPENAI_API_KEY` | Provider credential; never commit it |
| `TIDE_LLM_API_BASE` | `https://api.openai.com/v1` | OpenAI-compatible API base |
| `TIDE_LLM_MODEL` | `gpt-4o-mini` | Fixed challenge model; another value is rejected by default |
| `TIDE_ENFORCE_GPT4O_MINI` | `true` | Fails fast if the configured model differs |
| `TIDE_DB_PATH` | `/data/tide_mem.sqlite3` | Persistent SQLite database |
| `TIDE_LLM_MAX_CONCURRENCY` | `16` | Internal upstream-call concurrency |
| `TIDE_RETRIEVAL_CANDIDATE_LIMIT` | `220` | Maximum fused candidates before final selection |
| `TIDE_RERANK_CANDIDATE_LIMIT` | `80` | Maximum evidence snippets sent to the reranker |
| `TIDE_TTL_DAYS` | `30` | Automatic retention limit |
| `TIDE_REQUIRE_AUTH` | `true` | Require Add/Search authentication |

All configuration fields are documented in [`.env.example`](.env.example).

## Tests and release checks

```bash
pip install -r requirements-dev.txt
pytest -q
python -m compileall -q tide_mem scripts
python scripts/check_submission.py
```

The test suite verifies:

- exact synchronous Add and Search response shapes;
- public health and private Add/Search authentication;
- strict `user_id` isolation;
- idempotent Add retries;
- `top_k` enforcement;
- temporal update preference;
- request validation failures.

A GitHub Actions workflow runs the same tests on every push.

## Hosted deployment and application package

Use [`docs/ACCOUNT_HANDOFF.md`](docs/ACCOUNT_HANDOFF.md) for the browser-authorization flow and [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for Render or self-managed hosting. The form should bind:

- Add URL: `https://<your-domain>/v1/memory/add`
- Search URL: `https://<your-domain>/v1/memory/search`
- Health URL: `https://<your-domain>/health`
- Authentication: `X-Api-Key`
- Fixed version: tag `v0.1.0-amc2026` plus its commit SHA

Never put the Eval/Leaderboard Key or Memory System Key in the repository, URL, screenshot, or public issue.

After Render reports the service healthy, double-click
`VERIFY_AND_PREPARE_SUBMISSION.cmd`, or run the hosted verifier below. The key
is read through a hidden prompt and is not placed on the command line or written
to disk:

```powershell
.\scripts\verify_hosted.ps1 -BaseUrl https://<service>.onrender.com
```

A passing run creates private ready-to-paste application files under the
ignored `submission-private/` directory and configures a six-hourly public
health check in GitHub Actions. `scripts/build_application.py` remains
available as a manual fallback. Neither path writes the Memory System Key or
provider key.

## Security and data handling

- Request bodies, questions, options, and retrieved evidence are not written to application logs.
- Evaluation data is used only for memory evaluation, not training or analytics.
- TTL cleanup removes stored evidence after 30 days by default.
- Source text and questions are treated as untrusted data in LLM prompts.
- All SQL is parameterized, and all retrieval paths require an exact `user_id` predicate.

See [`docs/SECURITY_AND_DATA.md`](docs/SECURITY_AND_DATA.md).

## Reproducibility and originality disclosure

This repository is a new implementation prepared for the Agent Memory Challenge 2026. It does not copy another participant's memory-system implementation. It uses standard open-source libraries listed in `requirements.txt` and SQLite FTS5 from Python's standard SQLite distribution. The method is described fully in `docs/METHOD.md`; no benchmark questions, labels, private data, or hard-coded answers are included.

Before submission, use the generated files under `submission-private/`; keep the public bracketed files as reusable templates. Freeze the exact evaluated commit and tag.

## Current limitations

- The initial release uses a single-node SQLite store. It is intended for a bounded evaluation run, not a multi-region commercial service.
- Structured extraction quality depends on `gpt-4o-mini`; immutable raw evidence limits damage from extraction omissions but does not eliminate them.
- No official benchmark score is reported until the platform runs Smoke and Full.
- The first submission targets **Textual Memory** only; Coding Memory should be a separately versioned extension rather than an untested last-minute branch.

## License

MIT. See [`LICENSE`](LICENSE).
