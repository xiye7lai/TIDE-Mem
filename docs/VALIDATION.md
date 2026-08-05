# Local validation report

Validation date: **2026-08-05**

Release candidate: `v0.1.0-amc2026`

This report is deliberately limited to tests actually run in the preparation environment. It is **not** an official Agent Memory Challenge result and does not estimate the final leaderboard score.

## Automated repository tests

Command:

```bash
PYTHONPATH=. pytest -q
```

Result:

```text
15 passed
```

Covered behavior:

- public health endpoint;
- Add/Search authentication;
- exact Add success schema and ID echo;
- exact Search top-level object and `data` array;
- immediate retrieval after Add;
- strict request validation;
- hard `user_id` isolation;
- idempotent same-identity Add replay;
- rejection of a reused `request_id` across identity boundaries;
- `top_k` enforcement;
- temporal current-state preference and cross-Add reuse of stable same-user state keys;
- complete API-mode extraction → planning → reranking chain using a mocked `gpt-4o-mini` Chat Completions transport;
- private application-file generation and rejection of malformed repository URLs, base URLs, commit SHAs, and email addresses.

## Repository, deployment, and packaging checks

The following checks passed in the preparation environment:

```text
git diff --check
python -m compileall -q tide_mem scripts tests
bash -n deploy/docker-entrypoint.sh
python scripts/check_submission.py
YAML parsing: render.yaml and all three GitHub Actions workflows
```

The readiness checker found no tracked runtime database or recognized secret pattern. Public application templates intentionally retain identity/URL placeholders; the private generator removes them after deployment without reading or writing any API key.

The Windows account-handoff path now includes:

- browser-based GitHub CLI authorization rather than a pasted PAT;
- isolated `.venv` setup plus public repository creation, push, annotated tag, Release, CI, and tagged container workflow;
- account-specific Render service naming;
- Render Blueprint with a paid persistent disk and generated Memory System Key;
- hidden-key public Smoke verification;
- exact local/public commit consistency checks and Release-attached GHCR digest recovery;
- ready-to-paste private application files;
- a six-hourly public `/health` workflow configured after successful deployment.

## External-style smoke test

A local Uvicorn process was started with the same HTTP routes and authentication. The external client `scripts/smoke_test.py` was run against the process.

Result:

```json
{
  "status": "PASS",
  "checks": [
    "public health",
    "private Add/Search auth",
    "exact synchronous Add response",
    "immediate retrieval",
    "top_k",
    "stable IDs",
    "idempotent Add replay",
    "user_id isolation"
  ]
}
```

## Synthetic concurrency test

The HTTP/database layer was tested in deterministic heuristic mode with:

```text
64 Add requests at concurrency 16
64 Search requests at concurrency 16
```

Result:

```text
Add:    64/64 HTTP 200
Search: 64/64 HTTP 200
```

Observed local-machine figures in the final rerun were approximately 0.30 seconds wall time for Add and 0.19 seconds for Search. These values are environment-specific and must not be presented as production or official benchmark throughput.

## Important unvalidated items

- The preparation environment has no Docker daemon, so the Docker image was not built here. The public CI workflow builds it from the pushed frozen commit.
- The preparation environment has no PowerShell runtime, so the `.ps1` files were structurally reviewed but not executed locally. GitHub CI parses them with PowerShell before the submission should be treated as frozen.
- No real provider credential was used. The API-mode code path was tested with a mock transport, not with production `gpt-4o-mini` quota and latency.
- No official public/private benchmark suite, Answer model, Eval model, Smoke, or Full run was executed.
- Public HTTPS reachability and 30-day operational stability can only be established after the account owner approves the hosted deployment.

## Required production validation before Full

On Windows, use the bundled account-side flow:

```text
PUBLISH_TO_GITHUB.cmd
VERIFY_AND_PREPARE_SUBMISSION.cmd
```

The second script runs the external Smoke using a hidden Memory System Key. Only after it passes should the organizer-issued Smoke be launched against the exact commit/tag. Do not start Full until real provider requests are stable under the declared concurrency.
