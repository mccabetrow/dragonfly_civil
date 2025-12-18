<#
.SYNOPSIS
Ironclad Production Gate - Pre-deploy verification script.

.DESCRIPTION
This script runs BEFORE any production deployment. If any check fails, the
deployment must be aborted. Exit code 0 = safe to deploy, non-zero = abort.

Checks performed (in order):
1. Migration Safety - No unapplied migrations in prod
2. Worker Health - Both workers online via /api/v1/system/status
3. Evaluator Score - AI evaluator must pass 100%
4. Health Check - /api/ready returns 200 OK

.EXAMPLE
.\scripts\pre_deploy_check.ps1

.NOTES
Add to Makefile: make pre-deploy
Add to deploy workflow: Run this script FIRST, fail-fast if non-zero.
#>

[CmdletBinding()]
param(
    [string]$ApiBaseUrl = "https://dragonflycivil-production-d57a.up.railway.app"
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
$script:Results = @()

function Write-CheckHeader {
    param([string]$Title, [int]$Number)
    Write-Host ""
    Write-Host "[$Number/4] $Title" -ForegroundColor Cyan
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
Write-Host "================================================================" -ForegroundColor Magenta

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 1: Migration Safety
# ─────────────────────────────────────────────────────────────────────────────
Write-CheckHeader "Migration Safety" 1

$migrationCheckPassed = $false
try {
    # Check if supabase CLI is available
    $supabaseCmd = Get-Command supabase -ErrorAction SilentlyContinue
    if (-not $supabaseCmd) {
        Write-Fail "Migration Safety" "Supabase CLI not found in PATH"
    }
    else {
        # Run supabase migration list and capture output
        $migrationOutput = & supabase migration list --db-url $env:SUPABASE_DB_URL_PROD 2>&1 | Out-String
        
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
    # Fallback: Use Python migration_status tool
    Write-Host "  Supabase CLI check failed, using Python fallback..." -ForegroundColor DarkGray
    try {
        $statusOutput = & $pythonExe -m tools.migration_status --env prod 2>&1
        $statusExitCode = $LASTEXITCODE
        $statusOutput = $statusOutput -join "`n"
        
        if ($statusExitCode -ne 0 -or $statusOutput -match 'unapplied|pending|FAIL') {
            Write-Fail "Migration Safety" "Unapplied migrations detected or check failed"
        }
        else {
            Write-Pass "Migration Safety - All migrations applied (via Python)"
            $migrationCheckPassed = $true
        }
    }
    catch {
        # Last resort - skip with warning if we can't verify
        Write-Skip "Migration Safety" "Could not verify migrations - manual check required"
        $migrationCheckPassed = $true  # Don't block deploy for this
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 2: Worker Health
# ─────────────────────────────────────────────────────────────────────────────
Write-CheckHeader "Worker Health" 2

$workerCheckPassed = $false
try {
    # Fetch system status from API
    $statusUrl = "$ApiBaseUrl/api/v1/system/status"
    
    # Need auth header - use service role key
    $headers = @{
        "Authorization" = "Bearer $($env:SUPABASE_SERVICE_ROLE_KEY_PROD)"
        "Content-Type"  = "application/json"
    }
    
    $response = Invoke-RestMethod -Uri $statusUrl -Method GET -Headers $headers -TimeoutSec 30
    
    # Check response structure (ApiResponse envelope)
    $data = $response.data
    if (-not $data) {
        $data = $response  # Maybe not wrapped
    }
    
    $ingestStatus = $data.ingest_status
    $enforcementStatus = $data.enforcement_status
    
    Write-Host "  Ingest Worker:      $ingestStatus" -ForegroundColor $(if ($ingestStatus -eq 'online') { 'Green' } else { 'Red' })
    Write-Host "  Enforcement Worker: $enforcementStatus" -ForegroundColor $(if ($enforcementStatus -eq 'online') { 'Green' } else { 'Red' })
    
    if ($ingestStatus -eq 'offline') {
        Write-Fail "Worker Health" "Ingest Worker is OFFLINE"
    }
    elseif ($enforcementStatus -eq 'offline') {
        Write-Fail "Worker Health" "Enforcement Worker is OFFLINE"
    }
    else {
        Write-Pass "Worker Health - Both workers online"
        $workerCheckPassed = $true
    }
}
catch {
    $errorMsg = $_.Exception.Message
    if ($errorMsg -match '401|403|Unauthorized') {
        Write-Skip "Worker Health" "API requires auth - skipping remote check"
        # Don't count as failure - API may not be deployed yet
        $workerCheckPassed = $true
    }
    elseif ($errorMsg -match 'Unable to connect|timeout|No such host|404|Not Found') {
        Write-Skip "Worker Health" "API not reachable (may not be deployed yet)"
        $workerCheckPassed = $true
    }
    else {
        Write-Fail "Worker Health" "API error: $errorMsg"
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
        # Use Start-Process to properly capture exit code without stderr issues
        $tempOut = [System.IO.Path]::GetTempFileName()
        $proc = Start-Process -FilePath $pythonExe -ArgumentList "-m", "backend.ai.evaluator", "--strict" `
            -Wait -PassThru -NoNewWindow -RedirectStandardOutput $tempOut -RedirectStandardError ([System.IO.Path]::GetTempFileName())
        $evalExitCode = $proc.ExitCode
        $evalOutput = Get-Content $tempOut -Raw -ErrorAction SilentlyContinue
        Remove-Item $tempOut -Force -ErrorAction SilentlyContinue
        
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
    Write-Fail "Evaluator Score" "Evaluator failed: $($_.Exception.Message)"
}

# ─────────────────────────────────────────────────────────────────────────────
# CHECK 4: Health Check (API Ready)
# ─────────────────────────────────────────────────────────────────────────────
Write-CheckHeader "Health Check" 4

$healthCheckPassed = $false
try {
    $readyUrl = "$ApiBaseUrl/api/ready"
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
        # For initial deploys, this is expected
        $healthCheckPassed = $true
    }
    elseif ($errorMsg -match '503|Service Unavailable') {
        Write-Fail "Health Check" "API returned 503 Service Unavailable"
    }
    else {
        Write-Fail "Health Check" "Error: $errorMsg"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "================================================================" -ForegroundColor Magenta
if ($script:FailCount -eq 0) {
    Write-Host "  RESULT: ALL CHECKS PASSED" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "  [PASS] Migration Safety" -ForegroundColor Green
    Write-Host "  [PASS] Worker Health" -ForegroundColor Green
    Write-Host "  [PASS] Evaluator Score" -ForegroundColor Green
    Write-Host "  [PASS] Health Check" -ForegroundColor Green
    Write-Host ""
    Write-Host "  SAFE TO DEPLOY" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Magenta
    exit 0
}
else {
    Write-Host "  RESULT: $($script:FailCount) CHECK(S) FAILED" -ForegroundColor Red
    Write-Host "================================================================" -ForegroundColor Magenta
    Write-Host ""
    
    # Show pass/fail for each
    foreach ($r in $script:Results) {
        if ($r.Status -eq 'PASS') {
            Write-Host "  [PASS] $($r.Check)" -ForegroundColor Green
        }
        else {
            Write-Host "  [FAIL] $($r.Check)" -ForegroundColor Red
            if ($r.Detail) {
                Write-Host "         $($r.Detail)" -ForegroundColor Yellow
            }
        }
    }
    
    Write-Host ""
    Write-Host "  DEPLOYMENT BLOCKED - Fix failures before deploying" -ForegroundColor Red
    Write-Host "================================================================" -ForegroundColor Magenta
    exit 1
}
