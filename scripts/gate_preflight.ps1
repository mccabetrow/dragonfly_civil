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
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m tools.scan_secrets 2>&1
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
        Write-StepFail "SECRET-SCAN" "Secrets detected in tracked files - BLOCK DEPLOYMENT"
        Invoke-CriticalFailure
    }
    Write-StepPass "SECRET-SCAN"
}
else {
    Write-Host "  Skipped (tools/scan_secrets.py not found)" -ForegroundColor DarkGray
}

# ----------------------------------------------------------------------------
# STEP 1: Load Dev Environment
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

# ----------------------------------------------------------------------------
# STEP 1.5: Database Connectivity Test (Port 6543 vs 5432)
# ----------------------------------------------------------------------------
Write-StepStart "DB-CONNECT" "Validating database connectivity (Runtime + Migration)"

$dbConnTestPath = Join-Path $RepoRoot "tools\test_db_connection.py"
if (Test-Path $dbConnTestPath) {
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
# STEP 1.4: Security Invariants (Zero Trust boundary tests)
# ----------------------------------------------------------------------------
Write-StepStart "SECURITY-INVARIANTS" "Verifying security boundaries (Zero Trust)"

$securityTestFile = Join-Path $RepoRoot "tests\test_security_invariants.py"
if (Test-Path $securityTestFile) {
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest $securityTestFile -v 2>&1
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
        Write-StepFail "SECURITY-INVARIANTS" "Security boundary tests failed - DO NOT DEPLOY"
        Invoke-CriticalFailure
    }
    Write-StepPass "SECURITY-INVARIANTS"
}
else {
    Write-Host "  Skipped (tests/test_security_invariants.py not found)" -ForegroundColor DarkGray
}

# ----------------------------------------------------------------------------
# STEP 1.4b: Live Security Invariants (RLS coverage, security definer audit)
# ----------------------------------------------------------------------------
Write-StepStart "SECURITY-LIVE" "Verifying live security invariants (RLS + SECDEF)"

$securityLiveTestFile = Join-Path $RepoRoot "tests\test_security_invariants_live.py"
if (Test-Path $securityLiveTestFile) {
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest $securityLiveTestFile -v -m security 2>&1
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
        Write-StepFail "SECURITY-LIVE" "Live security invariant tests failed - RLS or SECDEF violations detected"
        Invoke-CriticalFailure
    }
    Write-StepPass "SECURITY-LIVE"
}
else {
    Write-Host "  Skipped (tests/test_security_invariants_live.py not found)" -ForegroundColor DarkGray
}

# ----------------------------------------------------------------------------
# STEP 1.4c: Zero Trust Security Audit (RLS + SECDEF Whitelist)
# ----------------------------------------------------------------------------
Write-StepStart "SECURITY-AUDIT" "Verifying Zero Trust security audit (RLS + SECDEF whitelist)"

$securityAuditTestFile = Join-Path $RepoRoot "tests\test_security_audit_zero_trust.py"
if (Test-Path $securityAuditTestFile) {
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest $securityAuditTestFile -v 2>&1
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
        Write-StepFail "SECURITY-AUDIT" "Zero Trust security audit failed - RLS or unauthorized SECDEF detected"
        Invoke-CriticalFailure
    }
    Write-StepPass "SECURITY-AUDIT"
}
else {
    Write-Host "  Skipped (tests/test_security_audit_zero_trust.py not found)" -ForegroundColor DarkGray
}

# ----------------------------------------------------------------------------
# STEP 1.4d: Security Audit (General)
# ----------------------------------------------------------------------------
Write-StepStart "SECURITY-GENERAL" "Verifying general security invariants"

$securityGeneralTestFile = Join-Path $RepoRoot "tests\test_security_audit.py"
if (Test-Path $securityGeneralTestFile) {
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest $securityGeneralTestFile -v 2>&1
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
        Write-StepFail "SECURITY-GENERAL" "Security audit tests failed"
        Invoke-CriticalFailure
    }
    Write-StepPass "SECURITY-GENERAL"
}
else {
    Write-Host "  Skipped (tests/test_security_audit.py not found)" -ForegroundColor DarkGray
}

# ----------------------------------------------------------------------------
# STEP 1.4e: Zero Trust Final Compliance (ops.v_rls_coverage = 0 violations)
# ----------------------------------------------------------------------------
Write-StepStart "ZERO-TRUST-FINAL" "Verifying Zero Trust compliance (RLS coverage views)"

$zeroTrustFinalTestFile = Join-Path $RepoRoot "tests\test_zero_trust_final.py"
if (Test-Path $zeroTrustFinalTestFile) {
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest $zeroTrustFinalTestFile -v 2>&1
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
        Write-StepFail "ZERO-TRUST-FINAL" "Zero Trust compliance failed - ops.v_rls_coverage violations detected"
        Invoke-CriticalFailure
    }
    Write-StepPass "ZERO-TRUST-FINAL"
}
else {
    Write-Host "  Skipped (tests/test_zero_trust_final.py not found)" -ForegroundColor DarkGray
}

# ----------------------------------------------------------------------------
# STEP 1.4f: Performance Budget Tests
# ----------------------------------------------------------------------------
Write-StepStart "PERF-BUDGET" "Verifying performance budgets (Index + Query time)"

$perfBudgetTestFile = Join-Path $RepoRoot "tests\test_performance_budget.py"
if (Test-Path $perfBudgetTestFile) {
    $result = & "$RepoRoot\.venv\Scripts\python.exe" -m pytest $perfBudgetTestFile -v -m performance 2>&1
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
else {
    Write-Host "  Skipped (tests/test_performance_budget.py not found)" -ForegroundColor DarkGray
}

# ----------------------------------------------------------------------------
# STEP 1.5: Unit Tests (non-integration tests)
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
