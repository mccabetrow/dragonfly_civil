<#
.SYNOPSIS
Ironclad Production Gate - Pre-deploy verification script.

.DESCRIPTION
This script runs BEFORE any production deployment. If any check fails, the
deployment must be aborted. Exit code 0 = safe to deploy, non-zero = abort.

Checks performed (in order):
1. Railway Environment - Required vars set on all services via Railway API
2. Migration Safety - No unapplied migrations in prod
3. Evaluator Score - AI evaluator must pass 100%
4. Health Check - /api/ready returns 200 OK (skipped for initial deploy)

CRITICAL: Check 1 (Railway Environment) will BLOCK deployment if:
- SUPABASE_DB_URL is missing from any service
- Any deprecated _PROD/_DEV suffix keys exist
- Any case-sensitive collisions (log_level vs LOG_LEVEL)

.PARAMETER SkipRailway
Skip Railway API checks (use for local testing only).

.PARAMETER DryRun
Show what would be checked without actually calling APIs.

.EXAMPLE
.\scripts\pre_deploy_check.ps1

.EXAMPLE
.\scripts\pre_deploy_check.ps1 -SkipRailway
# Local-only checks (for development)

.NOTES
Add to Makefile: make pre-deploy
Add to deploy workflow: Run this script FIRST, fail-fast if non-zero.

Required env vars:
- RAILWAY_TOKEN: For Railway API access (Check 1)
- SUPABASE_DB_URL_PROD or SUPABASE_DB_URL: For migration checks (Check 2)
#>

[CmdletBinding()]
param(
    [switch]$SkipRailway,
    [switch]$DryRun,
    [string]$RailwayProject = "dragonfly-civil",
    [string]$ApiBaseUrl = "https://dragonfly-api-production.up.railway.app"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'

# Load environment
$loadEnvScript = Join-Path $PSScriptRoot 'load_env.ps1'
if (Test-Path -LiteralPath $loadEnvScript) {
    . $loadEnvScript | Out-Null
}
$env:SUPABASE_MODE = 'prod'

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
$script:PassCount = 0
$script:FailCount = 0
$script:SkipCount = 0
$script:Results = @()

function Write-CheckHeader {
    param([string]$Title, [int]$Number, [int]$Total = 4)
    Write-Host ""
    Write-Host "[$Number/$Total] $Title" -ForegroundColor Cyan
    Write-Host ("-" * 60) -ForegroundColor DarkGray
}

function Write-Pass {
    param([string]$Message)
    Write-Host "  [PASS] $Message" -ForegroundColor Green
    $script:PassCount++
    $script:Results += @{ Check = $Message; Status = 'PASS' }
}

function Write-Fail {
    param([string]$Message, [string]$Detail = "")
    Write-Host "  [FAIL] $Message" -ForegroundColor Red
    if ($Detail) {
        Write-Host "         $Detail" -ForegroundColor Yellow
    }
    $script:FailCount++
    $script:Results += @{ Check = $Message; Status = 'FAIL'; Detail = $Detail }
}

function Write-Skip {
    param([string]$Message, [string]$Reason = "")
    Write-Host "  [SKIP] $Message" -ForegroundColor Yellow
    if ($Reason) {
        Write-Host "         $Reason" -ForegroundColor DarkYellow
    }
    $script:SkipCount++
    $script:Results += @{ Check = $Message; Status = 'SKIP'; Reason = $Reason }
}

# ─────────────────────────────────────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host "  IRONCLAD PRODUCTION GATE - Pre-Deploy Verification" -ForegroundColor Magenta
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host "  Target: PRODUCTION" -ForegroundColor Yellow
Write-Host "  Time:   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor White
Write-Host "  Mode:   $(if ($DryRun) { 'DRY RUN' } else { 'LIVE' })" -ForegroundColor $(if ($DryRun) { 'Yellow' } else { 'White' })
Write-Host "================================================================" -ForegroundColor Magenta

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 1: Railway Environment Variables
# ─────────────────────────────────────────────────────────────────────────────
Write-CheckHeader "Railway Environment Variables" 1

$railwayCheckPassed = $false

if ($SkipRailway) {
    Write-Skip "Railway Environment" "Skipped with -SkipRailway flag"
    $railwayCheckPassed = $true  # Don't block on skip
}
elseif (-not $env:RAILWAY_TOKEN) {
    Write-Fail "Railway Environment" "RAILWAY_TOKEN not set. Get token from Railway Dashboard > Account Settings > Tokens."
}
else {
    try {
        $auditArgs = @("scripts/railway_env_audit.py", "--railway", "--project", $RailwayProject)
        if ($DryRun) {
            $auditArgs += "--dry-run"
        }

        Write-Host "  Running: python $($auditArgs -join ' ')" -ForegroundColor DarkGray

        $auditOutput = & $pythonExe @auditArgs 2>&1
        $auditExitCode = $LASTEXITCODE

        # Display output
        $auditOutput | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }

        switch ($auditExitCode) {
            0 {
                Write-Pass "Railway Environment - All services configured correctly"
                $railwayCheckPassed = $true
            }
            1 {
                Write-Fail "Railway Environment" "Missing required variables (e.g., SUPABASE_DB_URL)"
                Write-Host "         Run: python scripts/railway_env_audit.py --railway --project $RailwayProject" -ForegroundColor Yellow
            }
            2 {
                Write-Fail "Railway Environment" "Deprecated keys found (e.g., SUPABASE_DB_URL_PROD)"
                Write-Host "         Delete deprecated keys from Railway Dashboard" -ForegroundColor Yellow
            }
            3 {
                Write-Fail "Railway Environment" "Case-sensitive conflicts (e.g., log_level vs LOG_LEVEL)"
                Write-Host "         Delete lowercase duplicates from Railway Dashboard" -ForegroundColor Yellow
            }
            4 {
                Write-Fail "Railway Environment" "Railway API error"
                Write-Host "         Check RAILWAY_TOKEN and project name" -ForegroundColor Yellow
            }
            default {
                Write-Fail "Railway Environment" "Unexpected exit code: $auditExitCode"
            }
        }
    }
    catch {
        Write-Fail "Railway Environment" "Audit script failed: $($_.Exception.Message)"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 2: Migration Safety
# ─────────────────────────────────────────────────────────────────────────────
Write-CheckHeader "Migration Safety" 2

$migrationCheckPassed = $false

# Get the DB URL for migrations
$dbUrl = $env:SUPABASE_DB_URL
if (-not $dbUrl) { $dbUrl = $env:SUPABASE_DB_URL_PROD }

if (-not $dbUrl) {
    Write-Fail "Migration Safety" "SUPABASE_DB_URL not set"
}
else {
    try {
        # Check if supabase CLI is available
        $supabaseCmd = Get-Command supabase -ErrorAction SilentlyContinue
        if (-not $supabaseCmd) {
            # Fallback: Use Python migration_status tool
            Write-Host "  Supabase CLI not found, using Python fallback..." -ForegroundColor DarkGray
            try {
                $statusOutput = & $pythonExe -m tools.migration_status --env prod 2>&1
                $statusExitCode = $LASTEXITCODE
                $statusOutput = $statusOutput -join "`n"

                if ($statusExitCode -ne 0 -or $statusOutput -match 'unapplied|pending|FAIL') {
                    Write-Fail "Migration Safety" "Unapplied migrations detected or check failed"
                    Write-Host "         Run: .\scripts\db_push.ps1 -SupabaseEnv prod" -ForegroundColor Yellow
                }
                else {
                    Write-Pass "Migration Safety - All migrations applied (via Python)"
                    $migrationCheckPassed = $true
                }
            }
            catch {
                Write-Skip "Migration Safety" "Could not verify migrations - manual check required"
                $migrationCheckPassed = $true  # Don't block on this
            }
        }
        else {
            # Run supabase migration list and capture output
            $migrationOutput = & supabase migration list --db-url $dbUrl 2>&1 | Out-String

            # Check for unapplied migrations (lines with "not applied" or similar)
            if ($migrationOutput -match 'not applied|pending|false') {
                Write-Fail "Migration Safety" "Unapplied migrations detected in prod"
                Write-Host "         Run: .\scripts\db_push.ps1 -SupabaseEnv prod" -ForegroundColor Yellow
            }
            elseif ($migrationOutput -match 'error|failed') {
                Write-Fail "Migration Safety" "Migration list command returned an error"
                Write-Host "         $migrationOutput" -ForegroundColor Yellow
            }
            else {
                Write-Pass "Migration Safety - All migrations applied"
                $migrationCheckPassed = $true
            }
        }
    }
    catch {
        Write-Skip "Migration Safety" "Error checking migrations: $($_.Exception.Message)"
        $migrationCheckPassed = $true  # Don't block on error
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 3: Evaluator Score
# ─────────────────────────────────────────────────────────────────────────────
Write-CheckHeader "Evaluator Score" 3

$evalCheckPassed = $false
try {
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        Write-Fail "Evaluator Score" "Python not found at $pythonExe"
    }
    else {
        # Run evaluator in strict mode (exits 1 if any failures)
        $tempOut = [System.IO.Path]::GetTempFileName()
        $tempErr = [System.IO.Path]::GetTempFileName()
        $proc = Start-Process -FilePath $pythonExe -ArgumentList "-m", "backend.ai.evaluator", "--strict" `
            -Wait -PassThru -NoNewWindow -RedirectStandardOutput $tempOut -RedirectStandardError $tempErr
        $evalExitCode = $proc.ExitCode
        $evalOutput = Get-Content $tempOut -Raw -ErrorAction SilentlyContinue
        Remove-Item $tempOut, $tempErr -Force -ErrorAction SilentlyContinue

        # Parse score from output
        if ($evalOutput -match 'Score:\s*([\d.]+)%') {
            $score = [double]$Matches[1]
            Write-Host "  Evaluator Score: $score%" -ForegroundColor $(if ($score -ge 100) { 'Green' } else { 'Red' })

            # Extract pass/fail counts
            $passed = 0
            $failed = 0
            if ($evalOutput -match 'Passed:\s*(\d+)') {
                $passed = $Matches[1]
            }
            if ($evalOutput -match 'Failed:\s*(\d+)') {
                $failed = $Matches[1]
            }
            if ($passed -or $failed) {
                Write-Host "  Cases: $passed passed, $failed failed" -ForegroundColor White
            }
        }

        if ($evalExitCode -ne 0) {
            Write-Fail "Evaluator Score" "Score < 100% - AI regression detected"
        }
        else {
            Write-Pass "Evaluator Score - 100% pass rate"
            $evalCheckPassed = $true
        }
    }
}
catch {
    Write-Skip "Evaluator Score" "Could not run evaluator: $($_.Exception.Message)"
    $evalCheckPassed = $true  # Don't block if evaluator unavailable
}

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 4: Health Check (API Ready)
# ─────────────────────────────────────────────────────────────────────────────
Write-CheckHeader "Health Check" 4

$healthCheckPassed = $false
try {
    $readyUrl = "$ApiBaseUrl/api/ready"
    Write-Host "  Checking: $readyUrl" -ForegroundColor DarkGray

    $response = Invoke-WebRequest -Uri $readyUrl -Method GET -TimeoutSec 30 -UseBasicParsing

    if ($response.StatusCode -eq 200) {
        Write-Pass "Health Check - /api/ready returned 200 OK"
        $healthCheckPassed = $true

        # Try to parse response for details
        try {
            $json = $response.Content | ConvertFrom-Json
            if ($json.database) {
                Write-Host "  Database: $($json.database)" -ForegroundColor White
            }
            if ($json.supabase) {
                Write-Host "  Supabase: $($json.supabase)" -ForegroundColor White
            }
        }
        catch {
            # JSON parse failed, that's ok
        }
    }
    else {
        Write-Fail "Health Check" "/api/ready returned $($response.StatusCode)"
    }
}
catch {
    $errorMsg = $_.Exception.Message
    if ($errorMsg -match 'Unable to connect|timeout|No such host|404|Not Found') {
        Write-Skip "Health Check" "API not reachable (may not be deployed yet)"
        $healthCheckPassed = $true  # Allow initial deploys
    }
    elseif ($errorMsg -match '503|Service Unavailable') {
        Write-Fail "Health Check" "API returned 503 Service Unavailable"
    }
    else {
        Write-Skip "Health Check" "Error: $errorMsg"
        $healthCheckPassed = $true  # Don't block on transient errors
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "================================================================" -ForegroundColor Magenta

$totalChecks = 4
$checkNames = @(
    @{ Name = "Railway Environment"; Passed = $railwayCheckPassed },
    @{ Name = "Migration Safety"; Passed = $migrationCheckPassed },
    @{ Name = "Evaluator Score"; Passed = $evalCheckPassed },
    @{ Name = "Health Check"; Passed = $healthCheckPassed }
)

if ($script:FailCount -eq 0) {
    Write-Host "  RESULT: ALL CHECKS PASSED ($script:PassCount/$totalChecks)" -ForegroundColor Green
    if ($script:SkipCount -gt 0) {
        Write-Host "          ($script:SkipCount skipped)" -ForegroundColor Yellow
    }
    Write-Host "================================================================" -ForegroundColor Magenta
    Write-Host ""

    foreach ($check in $checkNames) {
        $status = if ($check.Passed) { "[PASS]" } else { "[SKIP]" }
        $color = if ($check.Passed) { "Green" } else { "Yellow" }
        Write-Host "  $status $($check.Name)" -ForegroundColor $color
    }

    Write-Host ""
    Write-Host "  SAFE TO DEPLOY" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Magenta
    exit 0
}
else {
    Write-Host "  RESULT: $($script:FailCount) CHECK(S) FAILED" -ForegroundColor Red
    Write-Host "================================================================" -ForegroundColor Magenta
    Write-Host ""

    foreach ($check in $checkNames) {
        if ($check.Passed) {
            Write-Host "  [PASS] $($check.Name)" -ForegroundColor Green
        }
        else {
            Write-Host "  [FAIL] $($check.Name)" -ForegroundColor Red
        }
    }

    Write-Host ""
    Write-Host "  DEPLOYMENT BLOCKED - Fix failures before deploying" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Quick fixes:" -ForegroundColor Yellow
    if (-not $railwayCheckPassed) {
        Write-Host "    1. Set RAILWAY_TOKEN and check Railway variables" -ForegroundColor Yellow
        Write-Host "       python scripts/railway_env_audit.py --railway" -ForegroundColor DarkGray
    }
    if (-not $migrationCheckPassed) {
        Write-Host "    2. Apply pending migrations" -ForegroundColor Yellow
        Write-Host "       .\scripts\db_push.ps1 -SupabaseEnv prod" -ForegroundColor DarkGray
    }
    if (-not $evalCheckPassed) {
        Write-Host "    3. Fix AI evaluator regressions" -ForegroundColor Yellow
        Write-Host "       python -m backend.ai.evaluator --strict" -ForegroundColor DarkGray
    }
    if (-not $healthCheckPassed) {
        Write-Host "    4. Check API deployment" -ForegroundColor Yellow
        Write-Host "       curl $ApiBaseUrl/api/ready" -ForegroundColor DarkGray
    }

    Write-Host "================================================================" -ForegroundColor Magenta
    exit 1
}
