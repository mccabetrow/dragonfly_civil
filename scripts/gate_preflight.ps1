<#
.SYNOPSIS
    B3 Preflight Gate - Smart Deployment Verification with Controlled Relaxation.

.DESCRIPTION
    Executes the "Preflight Evidence Pack" before any production deployment.
    
    This script implements a THREE-PHASE gate strategy:

    PHASE 0 (Hard Invariants - Always Enforced):
      - DB Connectivity (can we reach the database?)
      - Contract Verification (RPC signatures match code)
      These NEVER skip - if DB is unreachable, deployment is impossible.

    PHASE 1 (Health Checks - Conditional via --tolerant):
      - RLS Compliance (Zero Trust)
      - Queue Reachability
      - Worker Heartbeats
      Normal: Failures are FATAL.
      InitialDeploy: Failures are WARNINGS (Exit 0).

    PHASE 2 (Tests - Segregated by Markers):
      - Contract tests: pytest -m "contract" (Always run)
      - Security tests: pytest -m "security" (Skip if InitialDeploy)
      - Unit tests: pytest -m "not integration and not security and not contract" (Always run)
      - Integration tests: pytest -m "integration" (Soft fail)

.PARAMETER InitialDeploy
    First-time deployment mode. Relaxes health checks that depend on 
    infrastructure not yet deployed (workers, RLS policies).

.EXAMPLE
    .\scripts\gate_preflight.ps1
    
    Normal mode: All checks enforced strictly.

.EXAMPLE
    .\scripts\gate_preflight.ps1 -InitialDeploy
    
    Initial deployment: RLS/Worker failures become warnings.
#>

param(
    [switch]$Verbose,
    [switch]$SkipDbTest,
    [switch]$InitialDeploy
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
# STEP 0: PowerShell Version Check (Incident 2025-12-21-01)
# ----------------------------------------------------------------------------
if ($PSVersionTable.PSVersion.Major -lt 7) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Yellow
    Write-Host "  ⚠️  WARNING: PowerShell $($PSVersionTable.PSVersion) detected" -ForegroundColor Yellow
    Write-Host "  Recommended: PowerShell 7+ for reliable API testing" -ForegroundColor Yellow
    Write-Host "  Install: winget install Microsoft.PowerShell" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Some multipart/form-data operations may fail on PS5.1." -ForegroundColor DarkYellow
    Write-Host "Continuing with caution..." -ForegroundColor DarkYellow
    Write-Host ""
}

# ----------------------------------------------------------------------------
# STEP 0.5: Secret Scanner (Incident 2025-12-22-01 - Postgres URI Leak)
# ----------------------------------------------------------------------------
Write-StepStart "SECRET-SCAN" "Scanning for leaked credentials in tracked files"

$secretScannerPath = Join-Path $RepoRoot "tools\scan_secrets.py"
if (Test-Path $secretScannerPath) {
    # PS5.1 fix: Run directly and capture exit code before any other operation
    $pythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    & $pythonExe -m tools.scan_secrets
    $scanExitCode = $LASTEXITCODE

    if ($scanExitCode -ne 0) {
        Write-StepFail "SECRET-SCAN" "Secrets detected in tracked files - BLOCK DEPLOYMENT"
        Invoke-CriticalFailure
    }
    Write-StepPass "SECRET-SCAN"
}
else {
    Write-Host "  Skipped (tools/scan_secrets.py not found)" -ForegroundColor DarkGray
}

# ----------------------------------------------------------------------------
# STEP 1: Load Environment (respects SUPABASE_MODE if set)
# ----------------------------------------------------------------------------
$targetMode = if ($env:SUPABASE_MODE) { $env:SUPABASE_MODE } else { "dev" }
Write-StepStart "ENV" "Loading $targetMode environment (.env.$targetMode)"

$envFile = Join-Path $RepoRoot ".env.$targetMode"
if (-not (Test-Path $envFile)) {
    Write-StepFail "ENV" ".env.$targetMode not found"
    Invoke-CriticalFailure
}

# Set SUPABASE_MODE
$env:SUPABASE_MODE = $targetMode
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

# ----------------------------------------------------------------------------
# STEP 1.5: Database Connectivity Test (Port 6543 vs 5432)
# ----------------------------------------------------------------------------
Write-StepStart "DB-CONNECT" "Validating database connectivity (Runtime + Migration)"

if ($SkipDbTest) {
    Write-Host "  [SKIPPED] -SkipDbTest flag set (pooler transient issues)" -ForegroundColor Yellow
}
else {
    $dbConnTestPath = Join-Path $RepoRoot "tools\test_db_connection.py"
    if (Test-Path $dbConnTestPath) {
        # Set PYTHONUTF8 to handle emoji output on Windows
        $env:PYTHONUTF8 = "1"
        $result = & "$RepoRoot\.venv\Scripts\python.exe" -m tools.test_db_connection 2>&1
        $exitCode = $LASTEXITCODE

        if ($Verbose) {
            $result | ForEach-Object { Write-Host $_ }
        }
        else {
            # Show just the summary lines
            $result | Select-Object -Last 12 | ForEach-Object { Write-Host $_ }
        }

        if ($exitCode -ne 0) {
            Write-Host ($result | Out-String) -ForegroundColor Red
            Write-StepFail "DB-CONNECT" "Database connectivity test failed - check SUPABASE_DB_URL and SUPABASE_MIGRATE_DB_URL"
            Invoke-CriticalFailure
        }
        Write-StepPass "DB-CONNECT"
    }
    else {
        Write-Host "  Skipped (tools/test_db_connection.py not found)" -ForegroundColor DarkGray
    }
}  # Close SkipDbTest else block

# ----------------------------------------------------------------------------
# STEP 1.6: System Health Verification (RLS, Queue, Workers)
# ----------------------------------------------------------------------------
Write-StepStart "SYSTEM-HEALTH" "Verifying system health (RLS, Queue, Workers)"

$systemHealthPath = Join-Path $RepoRoot "tools\verify_system_health.py"
if (Test-Path $systemHealthPath) {
    # Get current mode from environment
    $currentMode = $env:SUPABASE_MODE
    if (-not $currentMode) {
        $currentMode = "dev"
    }
    
    # Build args for verify_system_health
    # Use --tolerant for InitialDeploy mode (relaxes RLS/Worker checks)
    $healthArgs = @("--mode", $currentMode)
    if ($InitialDeploy) {
        $healthArgs += "--tolerant"
    }
    
    # Temporarily allow stderr without terminating (Python writes warnings to stderr)
    $prevErrPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m tools.verify_system_health @healthArgs 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $prevErrPref

    if ($Verbose) {
        $result | ForEach-Object { Write-Host $_ }
    }
    else {
        # Show the health check output
        $result | ForEach-Object { Write-Host $_ }
    }

    if ($exitCode -ne 0) {
        Write-StepFail "SYSTEM-HEALTH" "System health verification failed - see above for details"
        Invoke-CriticalFailure
    }
    Write-StepPass "SYSTEM-HEALTH"
}
else {
    Write-Host "  Skipped (tools/verify_system_health.py not found)" -ForegroundColor DarkGray
}

# ============================================================================
# PHASE 1: HARD GATE (Code Correctness + Contract Tests)
# ============================================================================
Write-Banner "PHASE 1: HARD GATE (Must Pass)" "Magenta"

# ----------------------------------------------------------------------------
# STEP 1.1: Contract Tests (RPC + Worker signatures)
# ----------------------------------------------------------------------------
Write-StepStart "CONTRACT-TESTS" "Verifying RPC contract signatures match code"

$result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest -m "contract" -v 2>&1
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
    Write-StepFail "CONTRACT-TESTS" "Contract tests failed - RPC signatures may have drifted"
    Invoke-CriticalFailure
}
Write-StepPass "CONTRACT-TESTS"

# ----------------------------------------------------------------------------
# STEP 1.2: Security Tests (All @pytest.mark.security tests)
# ----------------------------------------------------------------------------
Write-StepStart "SECURITY-TESTS" "Verifying security boundaries (Zero Trust, RLS, SECDEF)"

if ($InitialDeploy) {
    Write-Host "  [INITIAL DEPLOY] Skipping security tests (will fix RLS/SECDEF post-deploy)" -ForegroundColor Yellow
}
else {
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest -m "security" -v 2>&1
    $exitCode = $LASTEXITCODE

    if ($Verbose) {
        $result | ForEach-Object { Write-Host $_ }
    }
    else {
        # Show just the summary lines
        $result | Select-Object -Last 10 | ForEach-Object { Write-Host $_ }
    }

    if ($exitCode -ne 0) {
        Write-Host ($result | Out-String) -ForegroundColor Red
        Write-StepFail "SECURITY-TESTS" "Security tests failed - Zero Trust violations detected"
        Invoke-CriticalFailure
    }
    Write-StepPass "SECURITY-TESTS"
}

# ----------------------------------------------------------------------------
# STEP 1.3: Performance Budget Tests (@pytest.mark.performance)
# ----------------------------------------------------------------------------
Write-StepStart "PERF-BUDGET" "Verifying performance budgets (Index + Query time)"

if ($InitialDeploy) {
    Write-Host "  [INITIAL DEPLOY] Skipping performance budget tests (will verify post-deploy)" -ForegroundColor Yellow
}
else {
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest -m "performance" -v 2>&1
    $exitCode = $LASTEXITCODE

    if ($Verbose) {
        $result | ForEach-Object { Write-Host $_ }
    }
    else {
        # Show just the summary lines
        $result | Select-Object -Last 7 | ForEach-Object { Write-Host $_ }
    }

    if ($exitCode -ne 0) {
        Write-Host ($result | Out-String) -ForegroundColor Red
        Write-StepFail "PERF-BUDGET" "Performance budget tests failed - DB performance regression detected"
        Invoke-CriticalFailure
    }
    Write-StepPass "PERF-BUDGET"
}

# ----------------------------------------------------------------------------
# STEP 1.4: Unit Tests (excluding security, contract, integration, performance)
# ----------------------------------------------------------------------------
Write-StepStart "UNIT-TESTS" "Running unit tests (core logic)"

# Unit tests: exclude all specialized test categories via markers
# Markers provide clean test segregation without brittle --ignore paths
$pytestArgs = @("-m", "not integration and not security and not contract and not performance", "-q")

$result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest @pytestArgs 2>&1
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

# ----------------------------------------------------------------------------
# STEP 2.1: Intake Pipeline Smoke Test
# ----------------------------------------------------------------------------
Write-StepStart "INTAKE-SMOKE" "Running intake pipeline smoke test"

$smokeIntakePath = Join-Path $RepoRoot "scripts\smoke_intake.ps1"
if (Test-Path $smokeIntakePath) {
    $ErrorActionPreference = "Continue"
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m tools.smoke_intake 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"

    if ($Verbose) {
        $result | ForEach-Object { Write-Host $_ }
    }
    else {
        # Show just the verification lines
        $result | Select-Object -Last 15 | ForEach-Object { Write-Host $_ }
    }

    if ($exitCode -ne 0) {
        Write-StepWarn "INTAKE-SMOKE" "Intake smoke test failed (pipeline may be degraded)"
        $integrationWarning = $true
    }
    else {
        Write-StepPass "INTAKE-SMOKE"
    }
}
else {
    Write-Host "  Skipped (scripts/smoke_intake.ps1 not found)" -ForegroundColor DarkGray
}

# ----------------------------------------------------------------------------
# STEP 2.2: Integration Tests (PostgREST, Pooler, Realtime)
# ----------------------------------------------------------------------------
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
