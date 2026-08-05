# Account-side handoff: GitHub, Render, verification, and application

The repository automates every step that can be automated without exposing account credentials. The only remaining account-side actions are browser authorization, reviewing the paid hosting resources, and entering secrets into protected fields.

## Never send these credentials in chat

Do not send a GitHub password, personal access token, model-provider key, Memory System Key, Eval/Leaderboard Key, SSH private key, or Render recovery code. The included scripts deliberately use browser authorization and hidden prompts instead.

## Phase A — publish the frozen public repository

On Windows, double-click:

```text
PUBLISH_TO_GITHUB.cmd
```

Or run from PowerShell:

```powershell
.\scripts\publish_github.ps1
```

The script performs the following operations:

1. Creates an isolated `.venv`, installs the pinned dependencies there, and runs the Python tests, bytecode compilation, and submission safety check.
2. Installs Git, Python 3.11, or the official GitHub CLI with `winget` when any prerequisite is missing.
3. Opens GitHub's official browser authorization flow; it never accepts a token argument.
4. Reads the authenticated GitHub profile and asks for the submission contact, affiliation, and team name.
5. Re-attributes the frozen commit to the authenticated account, recreates the annotated tag, creates a new public repository, and pushes `main` and the tag.
6. Creates a GitHub Release and starts CI plus the tagged GHCR image build.
7. Saves non-secret account metadata under the ignored `submission-private/` directory.
8. Opens the repository-specific Render Blueprint deployment page.

The default repository name is `tide-mem`. If that name already exists, use a new empty name:

```powershell
.\scripts\publish_github.ps1 -RepoName tide-mem-amc2026
```

The script refuses to overwrite a repository that already has a `main` branch.

## Phase B — approve the Render Blueprint

The browser opens a URL of the following form:

```text
https://render.com/deploy?repo=https://github.com/OWNER/REPOSITORY
```

In Render:

1. Sign in and authorize access to the newly created public repository.
2. Review the Blueprint before approval. It creates one paid Starter Docker web service in Frankfurt and one 1 GB persistent disk.
3. Enter `TIDE_LLM_API_KEY` only in Render's protected secret field.
4. Leave `TIDE_LLM_MODEL=gpt-4o-mini` and the remaining fixed settings unchanged.
5. Approve the Blueprint and wait for `/health` to report healthy.

Render generates `TIDE_MEMORY_API_KEY`; it is not committed to GitHub. Retrieve it from the service's protected Environment page for the next phase and for the challenge's controlled secret field.

Automatic redeployment is disabled in `render.yaml`, so the initial hosted behavior remains bound to the frozen source unless a new version is explicitly deployed.

## Phase C — verify the public Add/Search service

On Windows, double-click `VERIFY_AND_PREPARE_SUBMISSION.cmd` and enter the public base URL. The equivalent PowerShell command is:

```powershell
.\scripts\verify_hosted.ps1 -BaseUrl https://YOUR-SERVICE.onrender.com
```

The script asks for the Render-generated Memory System Key using a hidden prompt. It does not put the key on the command line or write it to disk. It then checks:

- public health;
- rejection of anonymous Add;
- synchronous Add and immediate Search visibility;
- stable result IDs and `top_k` behavior;
- idempotent Add replay;
- exact cross-`user_id` isolation.

After a passing Smoke, it verifies the local and public frozen commit, retrieves the immutable GHCR digest attached to the GitHub Release when available, configures the repository’s non-secret public-base-URL variable, triggers the scheduled public health workflow, updates the repository homepage, and produces private, ready-to-paste files under `submission-private/`:

```text
SUBMISSION_APPLICATION_READY.md
SUBMISSION_NOTES_READY.txt
hosted-verification.txt
public-base-url.txt
container-image-identity.txt
```

A small hosted load check can be added only after the normal Smoke passes:

```powershell
.\scripts\verify_hosted.ps1 \
  -BaseUrl https://YOUR-SERVICE.onrender.com \
  -RunLoadTest
```

## Phase D — submit the application

Use the generated private files rather than editing the public templates. Confirm that the following values agree:

- public GitHub repository URL;
- exact 40-character commit SHA;
- annotated tag `v0.1.0-amc2026`;
- hosted Health/Add/Search URLs;
- authentication method `X-Api-Key`;
- declared Add concurrency 16, Search concurrency 16, and Top K 100.

Paste the Memory System Key only into the challenge form's controlled secret field. Do not add it to the application prose, GitHub repository, issue tracker, screenshots, or email.

## Manual fallbacks

- `scripts/build_application.py` can regenerate the private application files manually.
- `docs/DEPLOYMENT.md` includes a self-managed Docker Compose and Caddy path if Render is unsuitable.
