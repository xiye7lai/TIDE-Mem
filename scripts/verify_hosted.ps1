[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^https://')]
    [string]$BaseUrl,

    [switch]$RunLoadTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $RepoRoot
$BaseUrl = $BaseUrl.TrimEnd('/')

function Find-Python {
    $venvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) { return @($venvPython) }
    if (Get-Command 'py' -ErrorAction SilentlyContinue) {
        & py -3.11 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' *> $null
        if ($LASTEXITCODE -eq 0) { return @('py', '-3.11') }
        & py -3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' *> $null
        if ($LASTEXITCODE -eq 0) { return @('py', '-3') }
    }
    if (Get-Command 'python' -ErrorAction SilentlyContinue) {
        & python -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' *> $null
        if ($LASTEXITCODE -eq 0) { return @('python') }
    }
    throw 'Python 3.11 or newer was not found.'
}

function Invoke-Python([string[]]$PythonCommand, [string[]]$Arguments) {
    $exe = $PythonCommand[0]
    $prefix = if ($PythonCommand.Count -gt 1) { $PythonCommand[1..($PythonCommand.Count - 1)] } else { @() }
    & $exe @prefix @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed: $($Arguments -join ' ')" }
}

$python = Find-Python
$secure = Read-Host 'Paste the Render-generated TIDE_MEMORY_API_KEY (input is hidden)' -AsSecureString
$ptr = [IntPtr]::Zero
$plain = $null
try {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    if ([string]::IsNullOrWhiteSpace($plain)) {
        throw 'Memory System Key cannot be empty.'
    }
    $env:TIDE_MEMORY_API_KEY = $plain

    Invoke-Python $python @('scripts/smoke_test.py', '--base-url', $BaseUrl)

    if ($RunLoadTest) {
        Invoke-Python $python @(
            'scripts/load_test.py',
            '--base-url', $BaseUrl,
            '--records', '16',
            '--add-concurrency', '4',
            '--search-concurrency', '4'
        )
    }
} finally {
    Remove-Item Env:TIDE_MEMORY_API_KEY -ErrorAction SilentlyContinue
    if ($ptr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
    $plain = $null
    $secure = $null
}

$privateDir = Join-Path $RepoRoot 'submission-private'
New-Item -ItemType Directory -Path $privateDir -Force | Out-Null
Set-Content -Path (Join-Path $privateDir 'public-base-url.txt') -Value $BaseUrl -Encoding ASCII -NoNewline
Set-Content -Path (Join-Path $privateDir 'hosted-verification.txt') -Value "PASS`nbase_url=$BaseUrl`nverified_at_utc=$([DateTime]::UtcNow.ToString('o'))`n" -Encoding ASCII

$metadataPath = Join-Path $privateDir 'github-metadata.json'
if (Test-Path $metadataPath) {
    $metadata = Get-Content $metadataPath -Raw | ConvertFrom-Json
    $localSha = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the local Git commit.' }
    if ($localSha -ne [string]$metadata.commit_sha) {
        throw "Local commit $localSha does not match the published submission commit $($metadata.commit_sha)."
    }
    $imageIdentity = [string]$metadata.image

    if (Get-Command 'gh' -ErrorAction SilentlyContinue) {
        & gh auth status --hostname github.com *> $null
        if ($LASTEXITCODE -eq 0) {
            $digestDir = Join-Path $privateDir 'image-digest-download'
            Remove-Item $digestDir -Recurse -Force -ErrorAction SilentlyContinue
            New-Item -ItemType Directory -Path $digestDir -Force | Out-Null
            try {
                & gh release download ([string]$metadata.tag) `
                    --repo ([string]$metadata.repository) `
                    --pattern 'container-digest.txt' `
                    --dir $digestDir
                if ($LASTEXITCODE -eq 0) {
                    $digestPath = Join-Path $digestDir 'container-digest.txt'
                    $digest = (Get-Content $digestPath -Raw).Trim()
                    if ($digest -match '^sha256:[0-9a-fA-F]{64}$') {
                        $imageRepository = if ($metadata.PSObject.Properties.Name -contains 'image_repository') {
                            [string]$metadata.image_repository
                        } else {
                            ([string]$metadata.image) -replace (':' + [regex]::Escape([string]$metadata.tag) + '$'), ''
                        }
                        $imageIdentity = "$imageRepository@$($digest.ToLower())"
                        Set-Content -Path (Join-Path $privateDir 'container-image-identity.txt') `
                            -Value $imageIdentity -Encoding ASCII -NoNewline
                    } else {
                        Write-Warning 'The release digest asset is invalid; the tagged image identifier will be used.'
                    }
                } else {
                    Write-Warning 'The exact GHCR digest asset is not available; the tagged image identifier will be used.'
                }
            } finally {
                Remove-Item $digestDir -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }

    Set-Content -Path (Join-Path $privateDir 'container-image-identity.txt') `
        -Value $imageIdentity -Encoding ASCII -NoNewline

    Invoke-Python $python @(
        'scripts/build_application.py',
        '--name', [string]$metadata.contact_name,
        '--email', [string]$metadata.contact_email,
        '--affiliation', [string]$metadata.affiliation,
        '--team', [string]$metadata.team_members,
        '--repo-url', [string]$metadata.repository_url,
        '--base-url', $BaseUrl,
        '--commit-sha', [string]$metadata.commit_sha,
        '--image-digest', $imageIdentity,
        '--output-dir', $privateDir
    )
    Invoke-Python $python @('scripts/check_submission.py', '--strict-placeholders')

    if (Get-Command 'gh' -ErrorAction SilentlyContinue) {
        & gh auth status --hostname github.com *> $null
        if ($LASTEXITCODE -eq 0) {
            $remoteSha = (& gh api "repos/$($metadata.repository)/commits/main" --jq '.sha').Trim()
            if ($LASTEXITCODE -ne 0) { throw 'Could not verify the public GitHub main commit.' }
            if ($remoteSha -ne [string]$metadata.commit_sha) {
                throw "GitHub main commit $remoteSha does not match the frozen submission commit $($metadata.commit_sha)."
            }
            & gh variable set TIDE_PUBLIC_BASE_URL --repo ([string]$metadata.repository) --body $BaseUrl
            if ($LASTEXITCODE -eq 0) {
                Write-Host 'Configured the non-secret GitHub Actions health-monitor URL.'
                & gh workflow run hosted-health.yml --repo ([string]$metadata.repository)
                if ($LASTEXITCODE -ne 0) {
                    Write-Warning 'The endpoint is verified, but the first hosted-health workflow could not be triggered.'
                }
            } else {
                Write-Warning 'The endpoint is verified, but the GitHub Actions health-monitor variable could not be configured.'
            }
            & gh repo edit ([string]$metadata.repository) --homepage $BaseUrl
            if ($LASTEXITCODE -ne 0) {
                Write-Warning 'The endpoint is verified, but the repository homepage could not be updated.'
            }
        }
    }
} else {
    Write-Warning 'GitHub metadata was not found, so private application files were not generated automatically.'
}

Write-Host ''
Write-Host 'Hosted endpoint verification completed.' -ForegroundColor Green
Write-Host "Base URL: $BaseUrl"
Write-Host "Private verification and application files: $privateDir"
Write-Host 'The Memory System Key was not written to disk by this verifier.'
