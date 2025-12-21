<#
.SYNOPSIS
    Dragonfly Golden Path Verification

.DESCRIPTION
    One-command verification of the entire Dragonfly stack:
    1. Environment & Schema Check (tools/doctor.py)
    2. Code & Security Invariants Check (tests/test_invariants.py)
    3. End-to-End Functional Check (optional smoke test)

    Exit Codes:
    0 - All gates passed (GOLDEN PATH VERIFIED)
    1 - One or more gates failed

.PARAMETER Env
    Target environment: 'dev' or 'prod'. Default: dev

.PARAMETER SkipSmoke
    Skip the end-to-end smoke test (faster verification)

.PARAMETER Verbose
    Show verbose output from all checks

.EXAMPLE
    .\scripts\verify_golden_path.ps1
    .\scripts\verify_golden_path.ps1 -Env prod
    .\scripts\verify_golden_path.ps1 -SkipSmoke

.NOTES
    Author: Dragonfly Engineering
    Version: 1.0.0
#>

[CmdletBinding()]
param(
    [ValidateSet("dev", "prod")]
    [string]$Env = "dev",

    [switch]$SkipSmoke,

    [switch]$VerboseOutput
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ============================================================================
# CONFIGURATION
# ============================================================================

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

# Gate results tracking
$GatesPassed = 0
$GatesFailed = 0
$GateResults = @()

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

function Write-Banner {
    param([string]$Message)
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $Message" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host ""
}

function Write-GateStart {
    param([string]$GateName)
    Write-Host ""
    Write-Host ("-" * 70) -ForegroundColor DarkGray
    Write-Host "  GATE: $GateName" -ForegroundColor Yellow
    Write-Host ("-" * 70) -ForegroundColor DarkGray
}

function Write-GateResult {
    param(
        [string]$GateName,
        [bool]$Passed,
        [string]$Details = ""
    )

    if ($Passed) {
        Write-Host "[PASS] $GateName" -ForegroundColor Green
        $script:GatesPassed++
        $script:GateResults += @{ Name = $GateName; Passed = $true; Details = $Details }
    }
    else {
        Write-Host "[FAIL] $GateName" -ForegroundColor Red
        if ($Details) {
            Write-Host "       $Details" -ForegroundColor Red
        }
        $script:GatesFailed++
        $script:GateResults += @{ Name = $GateName; Passed = $false; Details = $Details }
    }
}

function Invoke-Gate {
    param(
        [string]$GateName,
        [scriptblock]$Command
    )

    Write-GateStart $GateName

    try {
        $output = & $Command 2>&1
        $exitCode = $LASTEXITCODE

        if ($VerboseOutput) {
            $output | ForEach-Object { Write-Host $_ }
        }

        if ($exitCode -eq 0) {
            Write-GateResult -GateName $GateName -Passed $true
            return $true
        }
        else {
            $errorDetails = ($output | Select-Object -Last 5) -join "`n"
            Write-GateResult -GateName $GateName -Passed $false -Details "Exit code: $exitCode"
            if (-not $VerboseOutput) {
                Write-Host "Last output:" -ForegroundColor DarkGray
                $output | Select-Object -Last 10 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
            }
            return $false
        }
    }
    catch {
        Write-GateResult -GateName $GateName -Passed $false -Details $_.Exception.Message
        return $false
    }
}

# ============================================================================
# PREFLIGHT CHECKS
# ============================================================================

Write-Banner "DRAGONFLY GOLDEN PATH VERIFICATION"

Write-Host "Environment: $Env" -ForegroundColor White
Write-Host "Project Root: $ProjectRoot" -ForegroundColor White
Write-Host "Python: $VenvPython" -ForegroundColor White
Write-Host "Skip Smoke: $SkipSmoke" -ForegroundColor White

# Verify Python exists
if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERROR] Python venv not found at: $VenvPython" -ForegroundColor Red
    Write-Host "Run: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

# Set environment
$env:SUPABASE_MODE = $Env

# Change to project root
Push-Location $ProjectRoot

try {
    # ========================================================================
    # GATE 1: Environment & Schema Check (tools/doctor.py)
    # ========================================================================
    $gate1Args = @("-m", "tools.doctor", "--env", $Env)
    if ($VerboseOutput) {
        $gate1Args += "--verbose"
    }

    $gate1Passed = Invoke-Gate -GateName "Environment & Schema (doctor.py)" -Command {
        & $VenvPython @gate1Args
    }

    # ========================================================================
    # GATE 2: Code & Security Invariants (tests/test_invariants.py)
    # ========================================================================
    $gate2Passed = Invoke-Gate -GateName "Invariant Enforcement (test_invariants.py)" -Command {
        & $VenvPython -m pytest tests/test_invariants.py -v --tb=short
    }

    # ========================================================================
    # GATE 3: End-to-End Functional Check (smoke test)
    # ========================================================================
    $gate3Passed = $true

    if (-not $SkipSmoke) {
        # Check if smoke test exists
        $smokeTestPath = Join-Path $ProjectRoot "tools\smoke_plaintiffs.py"
        if (Test-Path $smokeTestPath) {
            $gate3Passed = Invoke-Gate -GateName "End-to-End Smoke Test" -Command {
                & $VenvPython -m tools.smoke_plaintiffs --env $Env
            }
        }
        else {
            Write-Host "[SKIP] Smoke test not found at: $smokeTestPath" -ForegroundColor Yellow
            Write-Host "       Creating placeholder result..." -ForegroundColor DarkGray
            # Try running a basic connectivity test instead
            $gate3Passed = Invoke-Gate -GateName "Basic Connectivity Test" -Command {
                & $VenvPython -c "from src.supabase_client import create_supabase_client; c = create_supabase_client(); print('Supabase connection OK')"
            }
        }
    }
    else {
        Write-Host "[SKIP] Smoke test skipped (-SkipSmoke)" -ForegroundColor Yellow
    }

    # ========================================================================
    # SUMMARY
    # ========================================================================
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host ""

    $totalGates = $GatesPassed + $GatesFailed

    if ($GatesFailed -eq 0) {
        Write-Host "  [OK] GOLDEN PATH VERIFIED" -ForegroundColor Green -BackgroundColor DarkGreen
        Write-Host ""
        Write-Host "  All $totalGates gate(s) passed. System is ready for deployment." -ForegroundColor Green
        Write-Host ""
        Write-Host ("=" * 70) -ForegroundColor Cyan
        Write-Host ""

        # Show individual results
        Write-Host "Gate Results:" -ForegroundColor White
        foreach ($result in $GateResults) {
            $status = if ($result.Passed) { "[PASS]" } else { "[FAIL]" }
            $color = if ($result.Passed) { "Green" } else { "Red" }
            Write-Host "  $status $($result.Name)" -ForegroundColor $color
        }

        exit 0
    }
    else {
        Write-Host "  [X] GOLDEN PATH FAILED" -ForegroundColor Red -BackgroundColor DarkRed
        Write-Host ""
        Write-Host "  $GatesFailed of $totalGates gate(s) failed. Fix issues before deployment." -ForegroundColor Red
        Write-Host ""
        Write-Host ("=" * 70) -ForegroundColor Cyan
        Write-Host ""

        # Show individual results
        Write-Host "Gate Results:" -ForegroundColor White
        foreach ($result in $GateResults) {
            $status = if ($result.Passed) { "[PASS]" } else { "[FAIL]" }
            $color = if ($result.Passed) { "Green" } else { "Red" }
            Write-Host "  $status $($result.Name)" -ForegroundColor $color
            if (-not $result.Passed -and $result.Details) {
                Write-Host "         $($result.Details)" -ForegroundColor DarkRed
            }
        }

        Write-Host ""
        Write-Host "Recommended Actions:" -ForegroundColor Yellow
        Write-Host "  1. Fix failing gates before proceeding" -ForegroundColor White
        Write-Host "  2. Run with -VerboseOutput for detailed logs" -ForegroundColor White
        Write-Host "  3. Check tools/doctor.py output for schema issues" -ForegroundColor White
        Write-Host ""

        exit 1
    }

}
finally {
    Pop-Location
}
