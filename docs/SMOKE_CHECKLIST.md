# Pre-application and pre-Full checklist

## Repository

- [ ] Public GitHub repository exists and is reachable without login.
- [ ] `README.md` contains Docker, API entrypoints, configuration, and run steps.
- [ ] `make check` passes from a clean checkout.
- [ ] No `.env`, API key, database, log, benchmark answer, or private dataset is tracked.
- [ ] Identity/contact placeholders are replaced.
- [ ] Originality and reused-work disclosure is accurate.
- [ ] Commit is pushed and annotated tag `v0.1.0-amc2026` exists.
- [ ] Application records exact commit SHA and image digest.

## API

- [ ] Public HTTPS Health returns 2xx without authentication.
- [ ] Add URL is public and accepts the exact contract.
- [ ] Search URL is public and accepts the exact contract.
- [ ] X-Api-Key mode is selected consistently in the application.
- [ ] Unauthorized Add/Search returns 401.
- [ ] Add returns HTTP 200 only after records are immediately searchable.
- [ ] Add response echoes exact `request_id`, `user_id`, and `session_id` with `success=true`.
- [ ] Search returns `{"data": [...]}` rather than a top-level array or `items` wrapper.
- [ ] Every result has non-empty `id` and `content`.
- [ ] Search returns no more than requested `top_k`.
- [ ] No cross-user canary appears under another `user_id`.
- [ ] `scripts/smoke_test.py` completes successfully against the public domain.

## Model and method

- [ ] Add uses exact model name `gpt-4o-mini`.
- [ ] Search planning/reranking uses exact model name `gpt-4o-mini`.
- [ ] `TIDE_ENFORCE_GPT4O_MINI=true`.
- [ ] Heuristic mode is disabled in production.
- [ ] Search returns stored evidence, not a generated final answer or choice label.
- [ ] No public/private question hard-coding or gold-label access exists.

## Capacity and operations

- [ ] Provider quota supports at least declared Add/Search concurrency.
- [ ] Initial evaluation configuration is Add 16 / Search 16 / Top K 100.
- [ ] Persistent `/data` volume survives restart.
- [ ] `restart: unless-stopped` is active.
- [ ] Request-body and authorization-header logging is disabled.
- [ ] Disk space and host memory are adequate.
- [ ] Scheduled public health monitoring is configured (the included workflow runs every six hours).
- [ ] Hosted runtime can remain stable for at least 30 days.
- [ ] TTL cleanup is set to 30 days and backups follow the same retention policy.

## Submission timing

- [ ] Complete application and materials submitted before **2026-08-07 17:59 Europe/Paris**.
- [ ] Eval/Leaderboard Key and Memory System Key are stored privately and never placed in the repository/URL/screenshots.
- [ ] Smoke passes before Full.
- [ ] Formal Full is started only after version and capacity are frozen.
