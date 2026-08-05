# Production deployment for the self-hosted API route

The evaluated endpoint must be public, stable, and bound to the exact frozen source version. The recommended path uses the included Render Blueprint and does not require a domain or VPS. The later sections provide a self-managed Linux/Docker/Caddy fallback.

## 0. Recommended fast path: Render Blueprint

The root [`render.yaml`](../render.yaml) defines:

- one paid Starter Docker web service in Frankfurt;
- one 1 GB persistent disk mounted at `/data`;
- public HTTPS and `/health` checks;
- generated `TIDE_MEMORY_API_KEY`;
- a private prompt for `TIDE_LLM_API_KEY`;
- fixed `gpt-4o-mini` configuration;
- automatic deploys disabled after the initial version is created.

`PUBLISH_TO_GITHUB.cmd` creates the public repository and opens the correct deployment page automatically. The equivalent URL is:

```text
https://render.com/deploy?repo=https://github.com/<OWNER>/<REPOSITORY>
```

Review the billed resources, enter only the provider key, and approve the
Blueprint. The Docker entrypoint repairs ownership of the mounted database
directory before dropping to the unprivileged `tide` user. The application
binds to Render's `PORT` variable when present.

After deployment, copy the generated Memory System Key from Render's protected
environment settings and double-click `VERIFY_AND_PREPARE_SUBMISSION.cmd`, or
run the local verifier below. The key is requested through a hidden prompt and
is not written to disk:

```powershell
.\scripts\verify_hosted.ps1 -BaseUrl https://<service>.onrender.com
```

The Blueprint already sets `autoDeployTrigger: off`. A later change should be a disclosed commit/tag and explicit deployment rather than a silent mutation. A passing verifier also generates the private application files under ignored `submission-private/`, updates the repository homepage, and configures the six-hourly public health workflow.

## 1. Freeze the source before deployment

```bash
git status --short
make check
git add .
git commit -m "Release TIDE-Mem v0.1.0-amc2026"
git tag -a v0.1.0-amc2026 -m "Agent Memory Challenge 2026 initial submission"
git rev-parse HEAD
git show --no-patch --format=fuller v0.1.0-amc2026
```

Push the commit and annotated tag to a **public** repository. Record the commit SHA in the application template.

On Windows, double-click `PUBLISH_TO_GITHUB.cmd` or run `scripts/publish_github.ps1`. It automates testing, browser-based GitHub authorization, author attribution, repository creation, push, tag, topics, Release creation, CI/GHCR image launch, and opening the Render Blueprint. It never asks for a password or personal access token.

## 2. Generate secrets locally on the server

Generate two independent credentials. The Memory System Key is supplied to the competition through its controlled form; the provider key remains only on the host.

```bash
python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

Create `.env` from the example:

```bash
cp .env.example .env
chmod 600 .env
```

Set at least:

```dotenv
TIDE_MEMORY_API_KEY=<new participant-generated key>
TIDE_LLM_API_KEY=<provider key>
TIDE_LLM_API_BASE=https://api.openai.com/v1
TIDE_LLM_MODEL=gpt-4o-mini
TIDE_ENFORCE_GPT4O_MINI=true
TIDE_LLM_MODE=api
TIDE_LLM_REQUIRED=true
TIDE_DB_PATH=/data/tide_mem.sqlite3
TIDE_TTL_DAYS=30
TIDE_LLM_MAX_CONCURRENCY=16
```

Never copy the real `.env` into Git, a Docker image, a support ticket, or a screenshot.

## 3. Start the immutable application image

```bash
docker compose build --pull
docker compose up -d
docker compose ps
docker compose logs --tail=100 tide-mem
curl -fsS http://127.0.0.1:8000/health
```

The named Docker volume preserves `/data/tide_mem.sqlite3` across container restarts. `restart: unless-stopped` restores the service after a host reboot.

For an auditable image identity:

```bash
docker image inspect tide-mem:0.1.0-amc2026 --format '{{.Id}}'
```

Record the digest privately alongside the commit SHA.

## 4. Put HTTPS in front of port 8000

Bind the application port to localhost only when using a same-host reverse proxy. Change the Compose port mapping to:

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

A minimal Caddy configuration is included as `deploy/Caddyfile.example`. Replace the domain and route HTTPS traffic to `127.0.0.1:8000`.

The public URLs should be:

```text
https://memory.example.org/health
https://memory.example.org/v1/memory/add
https://memory.example.org/v1/memory/search
```

Do not put credentials in these URLs. Health remains public; Add/Search require the configured key.

## 5. Validate the public endpoint

```bash
python scripts/smoke_test.py \
  --base-url https://memory.example.org
```

The script reads `TIDE_MEMORY_API_KEY` from the environment by default, which
avoids placing the key in shell history. `--memory-key` remains available for
controlled local use.

The script verifies:

- unauthenticated health;
- rejected unauthenticated Add;
- exact Add success echo;
- immediate Search visibility;
- stable result structure;
- `top_k` enforcement;
- cross-`user_id` isolation;
- idempotent Add replay.

Save only the redacted success output. Do not save request payloads or keys in public CI logs.

## 6. Capacity settings for the initial Full

Use conservative evaluation settings first:

```text
Max Add concurrency: 16
Max Search concurrency: 16
Top K: 100
```

The API is asynchronous, but upstream model calls are gated by `TIDE_LLM_MAX_CONCURRENCY`. Increase it only when the provider quota, latency, and error rate have been tested. A 429 storm is worse than a lower declared concurrency.

Run the synthetic load client in heuristic mode on a staging deployment to verify HTTP/database behavior:

```bash
python scripts/load_test.py \
  --base-url https://staging-memory.example.org \
  --memory-key "$TIDE_MEMORY_API_KEY" \
  --add-concurrency 16 \
  --search-concurrency 16
```

Then perform a small API-mode test to validate provider quota without logging evaluation data.

## 7. Operational checks during the 30-day stability window

At least daily, check:

```bash
curl -fsS https://memory.example.org/health
docker compose ps
docker compose logs --since=24h tide-mem | tail -200
df -h
docker stats --no-stream
```

Monitor only status, latency, error class, CPU, memory, disk, and counts. Do not add request-body logging.

Keep the exact tagged version running. A security or availability hotfix should be committed, tagged as a new version, disclosed, and rebound before Full; do not silently change behavior after the formal version is accepted.

## 8. Backup and deletion

The default TTL removes records 30 days after persistence. To force cleanup:

```bash
docker compose exec tide-mem python -m scripts.purge --days 30
```

For an encrypted operational backup, stop writes or take a SQLite online backup and restrict access to essential operators. Delete evaluation-derived backups within the same retention window.

After the required availability and review period is complete, remove the deployment data unless the organizer has provided written permission for longer retention:

```bash
docker compose down
docker volume rm tide-mem_tide_mem_data
```

Check the actual volume name with `docker volume ls` before deletion.
