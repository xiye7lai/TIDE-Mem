[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$RepoName = "tide-mem",

    [ValidatePattern('^v[0-9A-Za-z._-]+$')]
    [string]$Tag = "v0.1.0-amc2026",

    [switch]$AllowExistingRepository,
    [switch]$DoNotOpenRender
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Read-Default([string]$Prompt, [string]$Default) {
    $suffix = if ($Default) { " [$Default]" } else { "" }
    $value = Read-Host "$Prompt$suffix"
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return $value.Trim()
}

function Refresh-ProcessPath {
    $paths = @(
        [Environment]::GetEnvironmentVariable("Path", "Machine"),
        [Environment]::GetEnvironmentVariable("Path", "User"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"),
        (Join-Path $env:ProgramFiles "Git\cmd"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\Scripts")
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $env:Path = ($paths | Select-Object -Unique) -join ";"
}

function Ensure-WingetPackage(
    [string]$Command,
    [string]$PackageId,
    [string]$DisplayName
) {
    if (Get-Command $Command -ErrorAction SilentlyContinue) { return }
    if (-not (Get-Command "winget" -ErrorAction SilentlyContinue)) {
        throw "$DisplayName is required, and Windows Package Manager (winget) is unavailable. Install $DisplayName from its official site, then rerun."
    }
    Write-Host "Installing $DisplayName through Windows Package Manager..."
    & winget install --id $PackageId --exact --source winget --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "$DisplayName installation failed." }
    Refresh-ProcessPath
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "$DisplayName was installed but is not visible in this terminal. Close this window and run PUBLISH_TO_GITHUB.cmd again."
    }
}

function Find-Python {
    if (Get-Command "py" -ErrorAction SilentlyContinue) {
        & py -3.11 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" *> $null
        if ($LASTEXITCODE -eq 0) { return @("py", "-3.11") }
        & py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" *> $null
        if ($LASTEXITCODE -eq 0) { return @("py", "-3") }
    }
    if (Get-Command "python" -ErrorAction SilentlyContinue) {
        & python -c "import sys; raise SystemExit(sys.version_info < (3, 11))" *> $null
        if ($LASTEXITCODE -eq 0) { return @("python") }
    }
    return $null
}

function Invoke-Python([string[]]$PythonCommand, [string[]]$Arguments) {
    $exe = $PythonCommand[0]
    $prefix = if ($PythonCommand.Count -gt 1) { $PythonCommand[1..($PythonCommand.Count - 1)] } else { @() }
    & $exe @prefix @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed: $($Arguments -join ' ')" }
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
Refresh-ProcessPath

Ensure-WingetPackage "git" "Git.Git" "Git for Windows"
if (-not (Find-Python)) {
    if (-not (Get-Command "winget" -ErrorAction SilentlyContinue)) {
        throw "Python 3.11 or newer is required, and Windows Package Manager (winget) is unavailable."
    }
    Write-Host "Installing Python 3.11 through Windows Package Manager..."
    & winget install --id Python.Python.3.11 --exact --source winget --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "Python 3.11 installation failed." }
    Refresh-ProcessPath
}
Ensure-WingetPackage "gh" "GitHub.cli" "GitHub CLI"

$bootstrapPython = Find-Python
if (-not $bootstrapPython) { throw "Python 3.11 or newer was not found after installation. Close this window and rerun PUBLISH_TO_GITHUB.cmd." }

& git rev-parse --is-inside-work-tree *> $null
if ($LASTEXITCODE -ne 0) {
    throw "This folder has no Git history. Use the account-assisted repository ZIP or clone the supplied .git.bundle, not the source-only ZIP."
}

$venvPythonPath = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPythonPath)) {
    Write-Host "Creating an isolated Python environment in .venv..."
    Invoke-Python $bootstrapPython @("-m", "venv", ".venv")
}
$python = @($venvPythonPath)

Write-Host "Installing pinned dependencies and running repository checks before account authorization..."
Invoke-Python $python @("-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements-dev.txt")
Invoke-Python $python @("-m", "pytest", "-q")
Invoke-Python $python @("-m", "compileall", "-q", "tide_mem", "scripts")
Invoke-Python $python @("scripts/check_submission.py")

$authStatus = (& gh auth status --hostname github.com 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) {
    Write-Host "GitHub's official browser authorization will open. Do not paste a password or personal access token into this script."
    & gh auth login --hostname github.com --git-protocol https --web --scopes workflow
    if ($LASTEXITCODE -ne 0) { throw "GitHub browser authorization did not complete." }
} elseif ($authStatus -notmatch '(?i)\bworkflow\b') {
    Write-Host "Refreshing GitHub authorization so the included Actions workflows can be pushed."
    & gh auth refresh --hostname github.com --scopes workflow
    if ($LASTEXITCODE -ne 0) { throw "GitHub authorization refresh did not complete." }
}
& gh auth setup-git --hostname github.com
if ($LASTEXITCODE -ne 0) { throw "Could not configure Git to use GitHub CLI authentication." }

$user = (& gh api user | ConvertFrom-Json)
if ($LASTEXITCODE -ne 0) { throw "Could not read the authenticated GitHub profile." }
$owner = [string]$user.login
$profileName = if ([string]::IsNullOrWhiteSpace([string]$user.name)) { $owner } else { [string]$user.name }
$authorEmail = if ([string]::IsNullOrWhiteSpace([string]$user.email)) {
    "$($user.id)+$owner@users.noreply.github.com"
} else {
    [string]$user.email
}

$gitAuthorName = Read-Default "Public Git commit author name" $profileName
$gitAuthorEmail = Read-Default "Public Git commit author email" $authorEmail
$contactName = Read-Default "Submission contact name" $profileName
$contactEmail = Read-Default "Submission contact email (stored only in ignored submission-private/)" ([string]$user.email)
while ([string]::IsNullOrWhiteSpace($contactEmail) -or $contactEmail -notmatch '^[^\s@]+@[^\s@]+\.[^\s@]+$') {
    $contactEmail = (Read-Host "Enter a valid submission contact email").Trim()
}
$affiliation = Read-Default "Affiliation or team" "Independent Researcher"
$teamMembers = Read-Default "Team members" "Solo participant"

$porcelain = (& git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect the Git working tree." }
if ($porcelain) {
    throw "The repository has uncommitted changes. Re-extract the clean account-assisted repository ZIP before publishing."
}

& git config user.name $gitAuthorName
& git config user.email $gitAuthorEmail
& git checkout main
if ($LASTEXITCODE -ne 0) { throw "Could not switch to the main branch." }

# Make the Render service slug account-specific before freezing the commit. This
# avoids collisions with other participants while preserving all runtime settings.
$renderServiceName = ("tide-mem-amc2026-" + $owner.ToLowerInvariant()) -replace '[^a-z0-9-]', '-'
$renderServiceName = ($renderServiceName -replace '-+', '-').Trim('-')
if ($renderServiceName.Length -gt 63) {
    $renderServiceName = $renderServiceName.Substring(0, 63).Trim('-')
}
$renderPath = Join-Path $Root 'render.yaml'
$renderText = [System.IO.File]::ReadAllText($renderPath)
$renderText = $renderText -replace '(?m)^    name:\s*[^\r\n]+$', "    name: $renderServiceName"
[System.IO.File]::WriteAllText($renderPath, $renderText, [System.Text.UTF8Encoding]::new($false))
& git add render.yaml
if ($LASTEXITCODE -ne 0) { throw "Could not stage the account-specific Render service name." }

# Re-author the frozen candidate under the user's chosen public Git identity.
& git commit --amend --reset-author --no-edit
if ($LASTEXITCODE -ne 0) { throw "Could not amend the release commit author." }

Invoke-Python $python @("scripts/check_submission.py")
& git diff --check
if ($LASTEXITCODE -ne 0) { throw "Git whitespace validation failed after freezing the account-specific commit." }
$afterAmendStatus = (& git status --porcelain)
if ($LASTEXITCODE -ne 0 -or $afterAmendStatus) {
    throw "The repository is not clean after freezing the account-specific commit."
}

& git tag -d $Tag *> $null
& git tag -a $Tag -m "Agent Memory Challenge 2026 initial submission"
if ($LASTEXITCODE -ne 0) { throw "Could not create annotated tag $Tag." }

$fullRepo = "$owner/$RepoName"
$repoUrl = "https://github.com/$fullRepo"
& gh repo view $fullRepo *> $null
$repoExists = ($LASTEXITCODE -eq 0)
if ($repoExists -and -not $AllowExistingRepository) {
    throw "Repository $fullRepo already exists. Rerun with another -RepoName."
}

if (-not $repoExists) {
    $existingOrigin = (& git remote get-url origin 2>$null)
    if ($existingOrigin) {
        Write-Host "Removing the package/bundle origin remote before creating $fullRepo."
        & git remote remove origin
        if ($LASTEXITCODE -ne 0) { throw "Could not remove the existing origin remote: $existingOrigin" }
    }
    & gh repo create $fullRepo --public --source . --remote origin --disable-wiki --description "Temporal, identity-isolated, dual-view evidence memory for Agent Memory Challenge 2026"
    if ($LASTEXITCODE -ne 0) { throw "Could not create $fullRepo." }
} else {
    $origin = (& git remote get-url origin 2>$null)
    if (-not $origin) {
        & git remote add origin "$repoUrl.git"
    } elseif ($origin -notmatch [regex]::Escape($fullRepo)) {
        throw "The existing origin remote points somewhere else: $origin"
    }
    $remoteRefs = (& git ls-remote origin)
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect the existing repository." }
    if ($remoteRefs) {
        throw "The existing repository is not empty. Use a new empty repository name instead of overwriting it."
    }
}

& git push --set-upstream origin main
if ($LASTEXITCODE -ne 0) { throw "Could not push main." }
& git push origin $Tag
if ($LASTEXITCODE -ne 0) { throw "Could not push tag $Tag." }

& gh repo edit $fullRepo --description "Temporal, identity-isolated, dual-view evidence memory for Agent Memory Challenge 2026" --add-topic agent-memory --add-topic memory-systems --add-topic fastapi --add-topic retrieval --add-topic amc2026 --enable-issues --enable-wiki=false
if ($LASTEXITCODE -ne 0) { Write-Warning "Repository was pushed, but some repository metadata could not be updated." }

& gh release view $Tag --repo $fullRepo *> $null
if ($LASTEXITCODE -ne 0) {
    $releaseNotes = @"
Initial public submission candidate for Agent Memory Challenge 2026.

- Track: Textual Memory
- Division: Academic Methods
- Route: Self-hosted Add/Search API
- Frozen tag: $Tag

No official leaderboard score is claimed in this release.
"@
    & gh release create $Tag --repo $fullRepo --verify-tag --title "TIDE-Mem $Tag" --notes $releaseNotes
    if ($LASTEXITCODE -ne 0) { Write-Warning "Code and tag were pushed, but the GitHub Release could not be created." }
}

$sha = (& git rev-parse HEAD).Trim()
$imageRepository = "ghcr.io/$($fullRepo.ToLower())"
$image = "$imageRepository`:$Tag"
$renderUrl = "https://render.com/deploy?repo=$repoUrl"
$submissionDir = Join-Path $Root "submission-private"
New-Item -ItemType Directory -Path $submissionDir -Force | Out-Null
$metadata = [ordered]@{
    owner = $owner
    repository = $fullRepo
    repository_url = $repoUrl
    commit_sha = $sha
    tag = $Tag
    image_repository = $imageRepository
    image = $image
    render_service_name = $renderServiceName
    git_author_name = $gitAuthorName
    git_author_email = $gitAuthorEmail
    contact_name = $contactName
    contact_email = $contactEmail
    affiliation = $affiliation
    team_members = $teamMembers
    actions_url = "$repoUrl/actions"
    render_deploy_url = $renderUrl
}
$metadata | ConvertTo-Json | Set-Content -Path (Join-Path $submissionDir "github-metadata.json") -Encoding UTF8

Write-Host ""
Write-Host "GitHub publication completed." -ForegroundColor Green
Write-Host "Repository: $repoUrl"
Write-Host "Commit:     $sha"
Write-Host "Tag:        $Tag"
Write-Host "GHCR image: $image"
Write-Host "Actions:    $repoUrl/actions"
Write-Host "Render:     $renderUrl"
Write-Host "Private local metadata: $submissionDir\github-metadata.json"
Write-Host "GitHub Actions now tests the repository and builds the tagged container image."

if (-not $DoNotOpenRender) {
    $answer = Read-Default "Open the Render Blueprint deployment page now? (Y/n)" "Y"
    if ($answer -notmatch '^[Nn]') {
        Start-Process $renderUrl
        Write-Host "Review the paid Starter service and 1 GB disk. Enter only TIDE_LLM_API_KEY in Render's protected secret field."
    }
}
