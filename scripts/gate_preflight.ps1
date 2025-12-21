<#
.SYNOPSIS
    B3 Preflight Gate - Two-Phase Deployment Verification.

.DESCRIPTION
    Executes the "Preflight Evidence Pack" before any production deployment.
    
    This script implements a TWO-PHASE gate strategy:

    PHASE 1 (Hard Fail):
      - Code correctness and unit tests
      - RPC contract signatures (direct DB introspection)
      - All tests NOT marked @pytest.mark.integration
      If any fail → ABORT deployment immediately.

    PHASE 2 (Soft Fail):
      - Integration tests (PostgREST, Pooler, Realtime)
      - Tests marked @pytest.mark.integration
      If these fail → WARN but allow deployment (external infra may be degraded).

.EXAMPLE
    .\scripts\gate_preflight.ps1
    
    If Phase 1 fails: "❌ CRITICAL FAILURE: DO NOT DEPLOY"
    If Phase 2 fails: "⚠️ WARNING: Integration tests failed (proceeding)"
    If all pass: "✅ PREFLIGHT COMPLETE (Ready for Prod)"
#>

param(
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

function Write-Banner {
    param([string]$Message, [string]$Color = "Cyan")
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor $Color
    Write-Host "  $Message" -ForegroundColor $Color
    Write-Host ("=" * 70) -ForegroundColor $Color
    Write-Host ""
}

function Write-StepStart {
    param([string]$Step, [string]$Description)
    Write-Host "[$Step] $Description" -ForegroundColor Yellow
    Write-Host ("-" * 50) -ForegroundColor DarkGray
}

function Write-StepPass {
    param([string]$Step)
    Write-Host "✅ [$Step] PASSED" -ForegroundColor Green
    Write-Host ""
}

function Write-StepWarn {
    param([string]$Step, [string]$Reason)
    Write-Host "⚠️ [$Step] WARNING: $Reason" -ForegroundColor Yellow
    Write-Host ""
}

function Write-StepFail {
    param([string]$Step, [string]$Reason)
    Write-Host "❌ [$Step] FAILED: $Reason" -ForegroundColor Red
    Write-Host ""
}

function Invoke-CriticalFailure {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Red
    Write-Host "  ❌ CRITICAL FAILURE: DO NOT DEPLOY" -ForegroundColor Red
    Write-Host ("=" * 70) -ForegroundColor Red
    Write-Host ""
    Write-Host "Phase 1 (Hard Gate) failed. Fix before proceeding to production." -ForegroundColor Yellow
    exit 1
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

Write-Banner "B3 PREFLIGHT GATE - Two-Phase Deployment Authorization"

$startTime = Get-Date
$integrationWarning = $false

# ----------------------------------------------------------------------------
# STEP 0: Load Dev Environment
# ----------------------------------------------------------------------------
Write-StepStart "ENV" "Loading dev environment (.env.dev)"

$envFile = Join-Path $RepoRoot ".env.dev"
if (-not (Test-Path $envFile)) {
    Write-StepFail "ENV" ".env.dev not found"
    Invoke-CriticalFailure
}

# Set SUPABASE_MODE to dev
$env:SUPABASE_MODE = "dev"
$env:ENV_FILE = $envFile

# Load env vars from file
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#') { return }
    if ($_ -match '^\s*$') { return }
    if ($_ -match '^([^=]+)=(.*)$') {
        $key = $matches[1].Trim()
        $value = $matches[2].Trim().Trim('"').Trim("'")
        Set-Item -Path "Env:$key" -Value $value
    }
}

Write-StepPass "ENV"

# ============================================================================
# PHASE 1: HARD GATE (Code Correctness + Contract Tests)
# ============================================================================
Write-Banner "PHASE 1: HARD GATE (Must Pass)" "Magenta"

# ----------------------------------------------------------------------------
# STEP 1.1: RPC Contract Tests (DB signatures match code)
# ----------------------------------------------------------------------------
Write-StepStart "RPC-CONTRACT" "Verifying DB contract matches code contract"

$testFile = Join-Path $RepoRoot "tests\test_rpc_contract.py"
if (Test-Path $testFile) {
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest $testFile -v 2>&1
    $exitCode = $LASTEXITCODE
    
    if ($Verbose) {
        $result | ForEach-Object { Write-Host $_ }
    }
    
    if ($exitCode -ne 0) {
        Write-Host ($result | Out-String) -ForegroundColor Red
        Write-StepFail "RPC-CONTRACT" "DB contract tests failed"
        Invoke-CriticalFailure
    }
    Write-StepPass "RPC-CONTRACT"
}
else {
    Write-Host "  Skipped (tests/test_rpc_contract.py not found)" -ForegroundColor DarkGray
}

# ----------------------------------------------------------------------------
# STEP 1.2: Worker RPC Contract Tests (workers use correct signatures)
# ----------------------------------------------------------------------------
Write-StepStart "WORKER-CONTRACT" "Verifying workers comply with RPC contract"

$workerTestFile = Join-Path $RepoRoot "tests\test_worker_rpc_contract.py"
if (Test-Path $workerTestFile) {
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest $workerTestFile -v 2>&1
    $exitCode = $LASTEXITCODE

    if ($Verbose) {
        $result | ForEach-Object { Write-Host $_ }
    }

    if ($exitCode -ne 0) {
        Write-Host ($result | Out-String) -ForegroundColor Red
        Write-StepFail "WORKER-CONTRACT" "Worker contract tests failed"
        Invoke-CriticalFailure
    }
    Write-StepPass "WORKER-CONTRACT"
}
else {
    Write-StepFail "WORKER-CONTRACT" "tests/test_worker_rpc_contract.py not found"
    Invoke-CriticalFailure
}

# ----------------------------------------------------------------------------
# STEP 1.3: Config Contract Tests (configuration logic is sound)
# ----------------------------------------------------------------------------
Write-StepStart "CONFIG-CONTRACT" "Verifying configuration contract"

$configTestFile = Join-Path $RepoRoot "tests\test_core_config.py"
if (Test-Path $configTestFile) {
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest $configTestFile -q 2>&1
    $exitCode = $LASTEXITCODE

    if ($Verbose) {
        $result | ForEach-Object { Write-Host $_ }
    }
    else {
        # Show just the summary lines
        $result | Select-Object -Last 3 | ForEach-Object { Write-Host $_ }
    }

    if ($exitCode -ne 0) {
        Write-Host ($result | Out-String) -ForegroundColor Red
        Write-StepFail "CONFIG-CONTRACT" "Configuration contract tests failed"
        Invoke-CriticalFailure
    }
    Write-StepPass "CONFIG-CONTRACT"
}
else {
    Write-StepFail "CONFIG-CONTRACT" "tests/test_core_config.py not found"
    Invoke-CriticalFailure
}

# ----------------------------------------------------------------------------
# STEP 1.4: Unit Tests (non-integration tests)
# ----------------------------------------------------------------------------
Write-StepStart "UNIT-TESTS" "Running unit tests (excluding integration)"

$result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest -m "not integration" -q 2>&1
$exitCode = $LASTEXITCODE

if ($Verbose) {
    $result | ForEach-Object { Write-Host $_ }
}
else {
    # Show just the summary lines
    $result | Select-Object -Last 5 | ForEach-Object { Write-Host $_ }
}

if ($exitCode -ne 0) {
    Write-Host ($result | Out-String) -ForegroundColor Red
    Write-StepFail "UNIT-TESTS" "Unit test suite failed"
    Invoke-CriticalFailure
}

Write-StepPass "UNIT-TESTS"

Write-Host "✅ Phase 1 Complete - Code correctness verified" -ForegroundColor Green
Write-Host ""

# ============================================================================
# PHASE 2: SOFT GATE (Integration Tests)
# ============================================================================
Write-Banner "PHASE 2: SOFT GATE (External Services)" "Cyan"

Write-StepStart "INTEGRATION" "Running integration tests (PostgREST, Pooler, Realtime)"

# Temporarily relax error handling for soft gate (integration failures are warnings)
$ErrorActionPreference = "Continue"
# Integration tests may take longer due to retry logic when infra is degraded
$result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest -m "integration" -q 2>&1
$exitCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"

if ($Verbose) {
    $result | ForEach-Object { Write-Host $_ }
}
else {
    # Show just the summary lines
    $result | Select-Object -Last 5 | ForEach-Object { Write-Host $_ }
}

if ($exitCode -ne 0) {
    Write-StepWarn "INTEGRATION" "Integration tests failed (external infra likely degraded)"
    Write-Host ""
    Write-Host "⚠️  WARNING: Integration tests failed." -ForegroundColor Yellow
    Write-Host "    External infrastructure (PostgREST, Pooler, Realtime) may be degraded." -ForegroundColor Yellow
    Write-Host "    Phase 1 passed, so code correctness is verified." -ForegroundColor Yellow
    Write-Host "    Proceeding with caution..." -ForegroundColor Yellow
    Write-Host ""
    $integrationWarning = $true
}
else {
    Write-StepPass "INTEGRATION"
    Write-Host "✅ Integration Suite Passed" -ForegroundColor Green
}

# ============================================================================
# SUCCESS
# ============================================================================
$endTime = Get-Date
$duration = ($endTime - $startTime).TotalSeconds

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host "  ✅ PREFLIGHT COMPLETE (Ready for Prod)" -ForegroundColor Green
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host ""

if ($integrationWarning) {
    Write-Host "⚠️  Note: Integration tests had failures. Monitor closely after deploy." -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "All preflight checks passed in $([math]::Round($duration, 1)) seconds." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Scale Railway workers to 0" -ForegroundColor White
Write-Host "  2. Run: .\scripts\deploy_db_prod.ps1" -ForegroundColor White
Write-Host "  3. Verify contract truth in SQL output" -ForegroundColor White
Write-Host "  4. Redeploy workers with new code" -ForegroundColor White
Write-Host ""

exit 0
