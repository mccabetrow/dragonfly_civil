<#
.SYNOPSIS
    Dragonfly Release Commander - Interactive Deployment Orchestrator

.DESCRIPTION
    This script acts as the "Release Commander" - an interactive guide that
    gates the human operator through the Golden Release procedure.
    
    It does NOT deploy code directly. Instead, it:
    - Runs automated verification at each phase
    - Pauses for human confirmation at critical steps
    - Provides clear ABORT signals if any check fails

    PHASES:
    1. Pre-Deployment: Preflight gate, scale workers to 0
    2. Database: Migrate, verify contract truth
    3. Deploy & Smoke: Deploy code, run smoke tests, scale up

.EXAMPLE
    .\release_commander.ps1
    
.EXAMPLE
    .\release_commander.ps1 -SkipPreflight  # Resume after preflight (dangerous)
#>

[CmdletBinding()]
param(
    [switch]$SkipPreflight
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptRoot
Set-Location $ProjectRoot

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

function Write-Banner {
    param([string]$Message, [string]$Color = "Cyan")
    Write-Host ""
    Write-Host ("╔" + ("═" * 68) + "╗") -ForegroundColor $Color
    Write-Host ("║" + $Message.PadLeft(35 + [math]::Floor($Message.Length / 2)).PadRight(68) + "║") -ForegroundColor $Color
    Write-Host ("╚" + ("═" * 68) + "╝") -ForegroundColor $Color
    Write-Host ""
}

function Write-Phase {
    param([string]$Phase, [string]$Title)
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Magenta
    Write-Host "  PHASE $Phase: $Title" -ForegroundColor Magenta
    Write-Host ("=" * 70) -ForegroundColor Magenta
    Write-Host ""
}

function Write-Step {
    param([string]$Step)
    Write-Host "  → $Step" -ForegroundColor Yellow
}

function Write-Pass {
    param([string]$Message)
    Write-Host "  ✅ $Message" -ForegroundColor Green
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  ❌ $Message" -ForegroundColor Red
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  ⚠️  $Message" -ForegroundColor Yellow
}

function Write-Info {
    param([string]$Message)
    Write-Host "  ℹ️  $Message" -ForegroundColor Cyan
}

function Invoke-Abort {
    param([string]$Reason)
    Write-Host ""
    Write-Host ("╔" + ("═" * 68) + "╗") -ForegroundColor Red
    Write-Host ("║" + "RELEASE ABORTED".PadLeft(42).PadRight(68) + "║") -ForegroundColor Red
    Write-Host ("╚" + ("═" * 68) + "╝") -ForegroundColor Red
    Write-Host ""
    Write-Fail $Reason
    Write-Host ""
    Write-Host "  Review the error above and fix before retrying." -ForegroundColor Yellow
    Write-Host "  See: docs/GOLDEN_RELEASE_PROCEDURE.md for rollback instructions." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

function Wait-ForConfirmation {
    param([string]$Prompt, [string]$ExpectedInput = "READY")
    Write-Host ""
    Write-Host "  ┌─────────────────────────────────────────────────────────────┐" -ForegroundColor Yellow
    Write-Host "  │ HUMAN ACTION REQUIRED                                       │" -ForegroundColor Yellow
    Write-Host "  └─────────────────────────────────────────────────────────────┘" -ForegroundColor Yellow
    Write-Host "  $Prompt" -ForegroundColor White
    Write-Host ""
    $response = Read-Host "  Type '$ExpectedInput' when complete (or 'ABORT' to cancel)"
    
    if ($response -eq "ABORT") {
        Invoke-Abort "User requested abort"
    }
    
    if ($response -ne $ExpectedInput) {
        Write-Warn "Expected '$ExpectedInput', got '$response'. Proceeding anyway..."
    }
    Write-Host ""
}

# =============================================================================
# MAIN RELEASE SEQUENCE
# =============================================================================

$startTime = Get-Date

Write-Banner "DRAGONFLY RELEASE COMMANDER" "Cyan"
Write-Host "  This script will guide you through the Golden Release procedure." -ForegroundColor White
Write-Host "  Follow each step carefully. Type 'ABORT' at any prompt to cancel." -ForegroundColor White
Write-Host ""
Write-Host "  Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor DarkGray
Write-Host ""

# =============================================================================
# PHASE 1: PRE-DEPLOYMENT
# =============================================================================
Write-Phase "1" "PRE-DEPLOYMENT CHECKS"

# Step 1.1: Load environment
Write-Step "Loading production environment..."
$env:SUPABASE_MODE = "prod"
$envFile = Join-Path $ProjectRoot ".env.prod"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*#') { return }
        if ($_ -match '^\s*$') { return }
        if ($_ -match '^([^=]+)=(.*)$') {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim().Trim('"').Trim("'")
            Set-Item -Path "Env:$key" -Value $value
        }
    }
    Write-Pass "Environment loaded from .env.prod"
}
else {
    Invoke-Abort ".env.prod not found. Create it before running release."
}

# Step 1.2: Run preflight gate
if (-not $SkipPreflight) {
    Write-Step "Running preflight gate..."
    Write-Info "This will run all Hard Gate checks (RPC-CONTRACT, WORKER-CONTRACT, CONFIG-CONTRACT, UNIT-TESTS)"
    Write-Host ""
    
    $preflightScript = Join-Path $ScriptRoot "gate_preflight.ps1"
    $result = & $preflightScript 2>&1
    $preflightExitCode = $LASTEXITCODE
    
    # Show summary
    $result | Select-Object -Last 20 | ForEach-Object { Write-Host "    $_" }
    
    if ($preflightExitCode -ne 0) {
        Invoke-Abort "Preflight gate failed. Fix all errors before deploying."
    }
    Write-Pass "Preflight gate passed"
}
else {
    Write-Warn "Skipping preflight gate (--SkipPreflight specified)"
    Write-Warn "This is DANGEROUS. Only use when resuming a failed release."
}

# Step 1.3: Human action - scale workers
Write-Pass "Pre-deployment checks complete"
Write-Host ""
Write-Host "  ┌─────────────────────────────────────────────────────────────┐" -ForegroundColor Green
Write-Host "  │ ✅ PHASE 1 COMPLETE                                         │" -ForegroundColor Green
Write-Host "  └─────────────────────────────────────────────────────────────┘" -ForegroundColor Green

Wait-ForConfirmation "Scale PROD workers to 0 in Railway now.`n  (Railway Dashboard → Workers → Scale to 0)"

# =============================================================================
# PHASE 2: DATABASE MIGRATION
# =============================================================================
Write-Phase "2" "DATABASE MIGRATION"

# Step 2.1: Human action - run migrations
Write-Step "Database migration required"
Write-Info "In a SEPARATE terminal, run:"
Write-Host ""
Write-Host "    .\scripts\deploy_db_prod.ps1" -ForegroundColor White
Write-Host ""
Write-Info "Wait for it to complete successfully before continuing."

Wait-ForConfirmation "Database migration is complete"

# Step 2.2: Auto-verify contract truth
Write-Step "Verifying database contract truth..."
$verifyScript = Join-Path $ScriptRoot "verify_db_contract.py"
$contractResult = & "$ProjectRoot\.venv\Scripts\python.exe" $verifyScript --env prod 2>&1
$contractExitCode = $LASTEXITCODE

# Show output
$contractResult | ForEach-Object { Write-Host "    $_" }

if ($contractExitCode -ne 0) {
    Write-Host ""
    Write-Host "  ┌─────────────────────────────────────────────────────────────┐" -ForegroundColor Red
    Write-Host "  │ ❌ ROLLBACK REQUIRED: DB CONTRACT MISMATCH                  │" -ForegroundColor Red
    Write-Host "  └─────────────────────────────────────────────────────────────┘" -ForegroundColor Red
    Write-Host ""
    Write-Host "  The database schema does not match the expected contract." -ForegroundColor Yellow
    Write-Host "  This means the migration may have failed or drifted." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  ROLLBACK STEPS:" -ForegroundColor Red
    Write-Host "    1. DO NOT deploy any code" -ForegroundColor White
    Write-Host "    2. Review the migration output for errors" -ForegroundColor White
    Write-Host "    3. Apply rollback migration if needed" -ForegroundColor White
    Write-Host "    4. Re-run this script from the beginning" -ForegroundColor White
    Write-Host ""
    Invoke-Abort "Database contract verification failed"
}

Write-Pass "Database contract verified"
Write-Host ""
Write-Host "  ┌─────────────────────────────────────────────────────────────┐" -ForegroundColor Green
Write-Host "  │ ✅ PHASE 2 COMPLETE                                         │" -ForegroundColor Green
Write-Host "  └─────────────────────────────────────────────────────────────┘" -ForegroundColor Green

# =============================================================================
# PHASE 3: DEPLOY & SMOKE
# =============================================================================
Write-Phase "3" "DEPLOY CODE & SMOKE TEST"

# Step 3.1: Human action - deploy code
Write-Step "Code deployment required"
Write-Info "In Railway Dashboard:"
Write-Host ""
Write-Host "    1. Deploy API service (trigger redeploy or push to main)" -ForegroundColor White
Write-Host "    2. Scale Workers to 1" -ForegroundColor White
Write-Host "    3. Wait for services to be 'Running'" -ForegroundColor White
Write-Host ""

Wait-ForConfirmation "API deployed and Workers scaled to 1"

# Step 3.2: Auto-run smoke tests
Write-Step "Running production smoke tests..."
$smokeScript = Join-Path $ScriptRoot "smoke_production.ps1"

# Get the API URL
$apiUrl = $env:DRAGONFLY_API_URL
if (-not $apiUrl) {
    $apiUrl = Read-Host "  Enter the production API URL (e.g., https://dragonflycivil-production.up.railway.app)"
}

Write-Info "Smoke testing: $apiUrl"
Write-Host ""

try {
    $smokeResult = & $smokeScript -ApiBaseUrl $apiUrl 2>&1
    $smokeExitCode = $LASTEXITCODE
    
    # Show output
    $smokeResult | ForEach-Object { Write-Host "    $_" }
    
    if ($smokeExitCode -ne 0) {
        Write-Host ""
        Write-Warn "Smoke test failed. Review the output above."
        Write-Host ""
        $continue = Read-Host "  Type 'PROCEED' to continue anyway, or 'ABORT' to cancel"
        if ($continue -ne "PROCEED") {
            Invoke-Abort "Smoke test failed and user chose to abort"
        }
        Write-Warn "Proceeding despite smoke test failure (user override)"
    }
    else {
        Write-Pass "Smoke tests passed"
    }
}
catch {
    Write-Warn "Smoke test script error: $_"
    $continue = Read-Host "  Type 'PROCEED' to continue anyway, or 'ABORT' to cancel"
    if ($continue -ne "PROCEED") {
        Invoke-Abort "Smoke test error and user chose to abort"
    }
}

# =============================================================================
# RELEASE COMPLETE
# =============================================================================
$endTime = Get-Date
$duration = ($endTime - $startTime).TotalMinutes

Write-Host ""
Write-Host ("╔" + ("═" * 68) + "╗") -ForegroundColor Green
Write-Host ("║" + "🎉 RELEASE SUCCESSFUL".PadLeft(45).PadRight(68) + "║") -ForegroundColor Green
Write-Host ("╚" + ("═" * 68) + "╝") -ForegroundColor Green
Write-Host ""
Write-Host "  Release completed in $([math]::Round($duration, 1)) minutes" -ForegroundColor White
Write-Host "  Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  POST-RELEASE ACTIONS:" -ForegroundColor Cyan
Write-Host "    1. Scale workers to desired count (2-4 for production)" -ForegroundColor White
Write-Host "    2. Monitor logs for 15 minutes" -ForegroundColor White
Write-Host "    3. Verify dashboard is working" -ForegroundColor White
Write-Host "    4. Notify team of successful release" -ForegroundColor White
Write-Host ""

exit 0
