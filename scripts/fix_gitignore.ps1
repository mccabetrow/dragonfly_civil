<#
.SYNOPSIS
    SEV-1 Response: Fix .gitignore and stop tracking secret files immediately.

.DESCRIPTION
    1. Ensures .gitignore exists with proper secret exclusions
    2. Removes tracked .env files from Git index (keeps local copies)
    3. Validates the fix was applied

.EXAMPLE
    .\scripts\fix_gitignore.ps1
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$GitIgnorePath = Join-Path $RepoRoot ".gitignore"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Red
Write-Host "  SEV-1 SECURITY RESPONSE: Fixing .gitignore and Git tracking  " -ForegroundColor Red
Write-Host "================================================================" -ForegroundColor Red
Write-Host ""

# =============================================================================
# STEP 1: Ensure .gitignore exists with required patterns
# =============================================================================
Write-Host "[1/4] Checking .gitignore..." -ForegroundColor Cyan

$RequiredPatterns = @(
    ".env",
    ".env.*",
    "*.env",
    ".env.dev",
    ".env.prod",
    ".env.local",
    ".env.staging",
    "*/.env",
    "*/.env.*",
    "*/.env.local",
    "judgment_ingestor/.env",
    "dragonfly-dashboard/.env",
    "dragonfly-dashboard/.env.local",
    "instance/",
    "tools/secrets/",
    "*.pem",
    "*.key",
    "*_rsa",
    "*_dsa",
    "*_ed25519",
    "*_ecdsa"
)

if (-not (Test-Path $GitIgnorePath)) {
    Write-Host "  Creating .gitignore (did not exist)..." -ForegroundColor Yellow
    $RequiredPatterns | Out-File -FilePath $GitIgnorePath -Encoding utf8
    Write-Host "  [OK] Created .gitignore with secret patterns" -ForegroundColor Green
}
else {
    Write-Host "  .gitignore exists, checking for missing patterns..." -ForegroundColor Gray
    $CurrentContent = Get-Content $GitIgnorePath -Raw
    $MissingPatterns = @()
    
    foreach ($pattern in $RequiredPatterns) {
        if ($CurrentContent -notmatch [regex]::Escape($pattern)) {
            $MissingPatterns += $pattern
        }
    }
    
    if ($MissingPatterns.Count -gt 0) {
        Write-Host "  Adding $($MissingPatterns.Count) missing patterns..." -ForegroundColor Yellow
        "`n# Added by SEV-1 fix_gitignore.ps1 - $(Get-Date -Format 'yyyy-MM-dd')" | Add-Content $GitIgnorePath
        $MissingPatterns | Add-Content $GitIgnorePath
        Write-Host "  [OK] Added missing patterns to .gitignore" -ForegroundColor Green
    }
    else {
        Write-Host "  [OK] All required patterns already present" -ForegroundColor Green
    }
}

# =============================================================================
# STEP 2: Remove .env files from Git tracking (CRITICAL)
# =============================================================================
Write-Host ""
Write-Host "[2/4] Removing .env files from Git index..." -ForegroundColor Cyan

$EnvFiles = @(".env", ".env.dev", ".env.prod", ".env.local", ".env.staging")
$RemovedCount = 0

foreach ($file in $EnvFiles) {
    $FilePath = Join-Path $RepoRoot $file
    if (Test-Path $FilePath) {
        # Check if file is tracked by Git
        $null = git ls-files --error-unmatch $file 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Untracking: $file" -ForegroundColor Yellow
            git rm --cached $file 2>$null
            $RemovedCount++
        }
        else {
            Write-Host "  Already untracked: $file" -ForegroundColor Gray
        }
    }
}

# Also check subdirectories
$SubdirEnvFiles = git ls-files --cached "*.env" ".env*" "*/.env*" 2>$null
if ($SubdirEnvFiles) {
    foreach ($file in ($SubdirEnvFiles -split "`n")) {
        if ($file) {
            Write-Host "  Untracking: $file" -ForegroundColor Yellow
            git rm --cached $file 2>$null
            $RemovedCount++
        }
    }
}

if ($RemovedCount -gt 0) {
    Write-Host "  [OK] Removed $RemovedCount file(s) from Git tracking" -ForegroundColor Green
}
else {
    Write-Host "  [OK] No tracked .env files found" -ForegroundColor Green
}

# =============================================================================
# STEP 3: Create tools/secrets/ directory (gitignored)
# =============================================================================
Write-Host ""
Write-Host "[3/4] Creating tools/secrets/ directory..." -ForegroundColor Cyan

$SecretsDir = Join-Path $RepoRoot "tools/secrets"
if (-not (Test-Path $SecretsDir)) {
    New-Item -ItemType Directory -Path $SecretsDir -Force | Out-Null
    $ReadmeContent = @"
# Secrets Directory

This directory is gitignored. Store local secrets here:
- Backup .env files
- API keys for testing
- Private keys

**NEVER commit files from this directory.**
"@
    $ReadmeContent | Out-File -FilePath (Join-Path $SecretsDir "README.md") -Encoding utf8
    Write-Host "  [OK] Created tools/secrets/ (gitignored)" -ForegroundColor Green
}
else {
    Write-Host "  [OK] tools/secrets/ already exists" -ForegroundColor Green
}

# =============================================================================
# STEP 4: Validate
# =============================================================================
Write-Host ""
Write-Host "[4/4] Validating fix..." -ForegroundColor Cyan

$TrackedEnvFiles = git ls-files --cached ".env*" "*.env" "*/.env*" 2>$null
if ($TrackedEnvFiles) {
    Write-Host "  [WARN] Some .env files are still tracked:" -ForegroundColor Red
    ($TrackedEnvFiles -split "`n") | ForEach-Object { 
        if ($_) { Write-Host "    - $_" -ForegroundColor Red }
    }
    Write-Host ""
    Write-Host "  Run manually: git rm --cached <file>" -ForegroundColor Yellow
    exit 1
}
else {
    Write-Host "  [OK] No .env files are tracked by Git" -ForegroundColor Green
}

# =============================================================================
# SUMMARY
# =============================================================================
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  GITIGNORE FIX COMPLETE                                       " -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Install pre-commit hook: python tools/install_hooks.py" -ForegroundColor White
Write-Host "  2. Stage the .gitignore:    git add .gitignore" -ForegroundColor White
Write-Host "  3. Commit the fix:          git commit -m 'security: fix .gitignore'" -ForegroundColor White
Write-Host "  4. If history is dirty:     See docs/RUNBOOK_HISTORY_SCRUB.md" -ForegroundColor White
Write-Host ""
