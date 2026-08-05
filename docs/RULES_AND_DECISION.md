# Agent Memory Challenge 2026: rules, route decision, and execution checklist

Checked against the official competition page, participation guide, API guide, evaluation page, and public evaluation repository on **2026-08-05**.

Official sources:

- Competition: https://agentmemories.ai/competition/
- Participation guide and API documentation: https://agentmemories.ai/home
- Public evaluation code: https://github.com/AML-memory/agent-memory-leaderboard

## 1. Deadline and what must be submitted

The first-cycle application deadline is **2026-08-07 23:59 UTC+8**. In Europe/Paris on that date, daylight-saving time is UTC+2, so the concrete local deadline is:

> **Friday, 2026-08-07 at 17:59 Europe/Paris.**

The official guide says the evaluation application and complete materials must be submitted by the deadline. Application review, deployment verification, Smoke, Full, and result review may continue according to the organizers' schedule, but incomplete materials, an unbuildable repository, or an unreachable API can miss the first board.

## 2. Recommended entry route

### Selected route

- **Evaluation type:** Textual Memory
- **Division:** Academic Methods
- **Submission route:** Self-hosted Add/Search API
- **Initial system:** TIDE-Mem `v0.1.0-amc2026`

### Why this route

The user specifically wants the evaluator/API-key flow. Under the official rules:

- an **Academic + self-hosted API** submission provides a public GitHub repository, fixed version, Add/Search URLs, authentication, and run instructions;
- after approval, this route receives an **Eval/Leaderboard Key**;
- an **Academic + code-only** submission also needs a public GitHub repository and Docker instructions, but the platform deploys it and does **not** issue an Eval Key;
- a commercial API can remain closed-source, but it enters a separate commercial board and is not the right choice for a new academic method.

Therefore, a public GitHub repository is not optional for the selected academic API route.

## 3. System/platform responsibility boundary

The participant implements only:

1. `Add`: receive source messages and finish memory processing/persistence;
2. `Search`: return ranked memory records or evidence.

The platform implements:

3. `Answer`: generate the final answer from returned evidence;
4. `Eval`: score and audit the answer.

Consequences:

- `Search` must **not** directly answer the question;
- it must not disguise a generated answer as a memory record;
- options may be used only to understand retrieval needs, not to choose or return an option label;
- no benchmark gold labels, hard-coded public questions, cross-sample state, human real-time answering, prompt injection, leakage, or score manipulation.

TIDE-Mem enforces this separation by making the Search LLM planner output evidence needs and the reranker output only candidate IDs/scores. Final Search content comes only from stored evidence records.

## 4. Exact synchronous API contract

### Health

- unauthenticated `GET`;
- any 2xx response is healthy;
- when no custom health URL is configured, the platform checks `/health` on the Add origin.

TIDE-Mem: `GET /health`.

### Add request

```json
{
  "request_id": "unique write request ID",
  "messages": [
    {
      "role": "user",
      "timestamp": 1704067200000,
      "content": "non-empty source memory text"
    }
  ],
  "user_id": "exact isolation boundary",
  "session_id": "source session identifier"
}
```

Rules:

- `timestamp` is optional Unix milliseconds;
- messages stay in source order;
- `session_id` organizes provenance but is not a Search filter;
- processing may be internally asynchronous, but the endpoint is externally synchronous;
- the memory must be committed and immediately searchable before HTTP 200;
- do not return HTTP 202, task IDs, polling URLs, or unnecessary memory IDs.

Required response:

```json
{
  "success": true,
  "request_id": "exact request value",
  "user_id": "exact request value",
  "session_id": "exact request value"
}
```

### Search request

```json
{
  "query": "original benchmark question",
  "options": ["optional choice A", "optional choice B"],
  "user_id": "same exact isolation boundary",
  "top_k": 100
}
```

Rules:

- `options` is omitted for open questions;
- the current contract does not send filters, rerank flags, or keyword-search flags;
- formal external evaluation fixes `top_k=100`;
- never return more than `top_k` records;
- retrieve only from the exact requested `user_id`.

Required response:

```json
{
  "data": [
    {
      "id": "stable non-empty record ID",
      "content": "non-empty evidence text",
      "score": 0.87,
      "created_at": "2026-07-01T12:00:00Z"
    }
  ]
}
```

`score` and `created_at` are optional; `data`, `id`, and `content` are mandatory. The platform preserves response order. No result means `{"data": []}`.

## 5. Authentication and keys

Supported Add/Search methods are `Token`, `Bearer`, and `X-Api-Key`. TIDE-Mem supports all three and recommends `X-Api-Key` for the application.

There are two different secrets:

- **Eval/Leaderboard Key:** issued by the organizers, used to create evaluation jobs and view private results;
- **Memory System Key:** generated by the participant, used by the platform to call this repository's Add/Search API.

Never place either key in:

- the public GitHub repository;
- a URL;
- screenshots;
- email or chat bodies;
- public issues or logs.

The checked-in `.env.example` contains placeholders only. The real `.env` is ignored by Git.

## 6. Version, originality, and reproducibility

Academic submissions must provide a public, verifiable GitHub repository and disclose:

- fixed source version and commit;
- README and full run steps;
- Docker command;
- API entry points;
- dependencies;
- original papers/repositories/authors for reused work;
- every method change.

Formal Full binds the score to the declared code, image, or API version. Smoke can be rerun after fixes before Full; treat Full as a one-shot frozen release for the cycle.

TIDE-Mem's recommended frozen identity is:

- semantic version: `0.1.0-amc2026`;
- Git tag: `v0.1.0-amc2026`;
- Docker image label: `tide-mem:0.1.0-amc2026`;
- commit: fill from `git rev-parse HEAD` after the public repository is created.

## 7. Runtime and capacity implications

The official public evaluation code discloses:

- Full task timeout: 72 hours;
- formal retrieval `top_k`: 100;
- Add default: 64 workers, 20-message chunks, 1200-second HTTP timeout;
- Search default: 32 workers, 1200-second timeout and retries;
- platform answer model: `gpt-4o-mini` at temperature 0.

The evaluation UI allows lower participant-selected concurrency. The conservative first submission setting is:

- **Max Add concurrency: 16**
- **Max Search concurrency: 16**
- internal `gpt-4o-mini` concurrency: 16

This trades speed for quota stability. Raise it only after a production-provider load test.

The Full checklist additionally requires the submitted Add/Search system itself to use `gpt-4o-mini`. TIDE-Mem fixes that model name by default and refuses another model unless the explicit enforcement switch is disabled. Keep enforcement enabled for the evaluated version.

## 8. Hosting and data requirements

A self-hosted API submission must:

- be publicly reachable from the platform;
- use a URL without embedded credentials;
- not resolve to private, loopback, or link-local addresses;
- preferably use HTTPS;
- remain stable and reachable for at least **30 days after submission**.

Evaluation data and derived copies may be used only to perform the current evaluation. They must not be used for training, fine-tuning, product analytics, dataset reconstruction, or sharing. Avoid unnecessary payload logs and delete the data within 30 days unless written permission says otherwise.

TIDE-Mem does not log request bodies and automatically purges evidence after 30 days by default.

## 9. What is already prepared in this repository

- [x] Exact Add request/response models
- [x] Exact Search request/response models
- [x] synchronous persistence before Add success
- [x] idempotent Add retries
- [x] public `/health`
- [x] Token, Bearer, and X-Api-Key authentication
- [x] hard `user_id` isolation in every retrieval query
- [x] `top_k` enforcement and stable record IDs
- [x] evidence-only Search design
- [x] `gpt-4o-mini` enforcement for Add/Search
- [x] Dockerfile and Compose deployment
- [x] persistent SQLite/FTS5 volume
- [x] 30-day TTL cleanup
- [x] local contract, isolation, idempotency, and temporal tests
- [x] external smoke-test client
- [x] application and submission-note templates
- [x] GitHub Actions CI

## 10. Remaining owner actions, in order

1. Replace the bracketed identity/contact fields in `docs/SUBMISSION_APPLICATION_ZH.md` and `SUBMISSION_NOTES.txt`.
2. Create a **public** GitHub repository and push this tree.
3. Run tests, commit, and create the immutable `v0.1.0-amc2026` tag.
4. Deploy that exact tag to a public HTTPS domain with a persistent `/data` volume.
5. Run `scripts/smoke_test.py` against the public domain and save its output privately.
6. Put the Add, Search, Health URLs and **Memory System Key** into the controlled application form—not the repository.
7. Submit the application and complete materials before **2026-08-07 17:59 Europe/Paris**.
8. After approval, use the issued Eval Key to run Smoke. Do not start Full until the exact version and provider quota are stable.
