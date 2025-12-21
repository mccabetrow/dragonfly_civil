<#
.SYNOPSIS
    Dragonfly Golden Path Deployment Gate
    Run this before every production deployment.

.DESCRIPTION
    This script performs comprehensive pre-deployment validation:
    1. Doctor Check - Environment consistency & connectivity
    2. Prod Gate - Required environment variables
    3. Security Tests - Migration security validation

    All gates must pass before deployment is allowed.

.EXAMPLE
    .\golden_gate.ps1

.EXAMPLE
    .\golden_gate.ps1 -Env prod -Verbose

.EXAMPLE
    .\golden_gate.ps1 -SkipTests  # Skip pytest (faster)
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidateSet("dev", "prod")]
    [string]$Env = "prod",

    [Parameter(Mandatory = $false)]
    [switch]$SkipTests,

    [Parameter(Mandatory = $false)]
    [switch]$Verbose
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptRoot

# Colors
function Write-Header {
    param([string]$Message)
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $Message" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host ""
}

function Write-Pass {
    param([string]$Message)
    Write-Host "✅ PASS: " -ForegroundColor Green -NoNewline
    Write-Host $Message
}

function Write-Fail {
    param([string]$Message)
    Write-Host "❌ FAIL: " -ForegroundColor Red -NoNewline
    Write-Host $Message
}

function Write-Info {
    param([string]$Message)
    Write-Host "ℹ️  INFO: " -ForegroundColor Blue -NoNewline
    Write-Host $Message
}

function Write-Step {
    param([string]$Step, [string]$Description)
    Write-Host ""
    Write-Host "[$Step] " -ForegroundColor Yellow -NoNewline
    Write-Host $Description
    Write-Host ("-" * 50)
}

# Track gate status
$GatesPassed = 0
$GatesFailed = 0

Write-Header "DRAGONFLY GOLDEN PATH GATE - $($Env.ToUpper())"

# Set environment
$env:SUPABASE_MODE = $Env
Write-Info "Environment set to: $Env"

# =============================================================================
# GATE 1: Doctor Check
# =============================================================================
Write-Step "GATE 1" "Doctor Check (Environment Consistency)"

try {
    $doctorArgs = @("-m", "tools.doctor")
    if ($Env) {
        $doctorArgs += @("--env", $Env)
    }
    if ($Verbose) {
        $doctorArgs += "--verbose"
    }

    $process = Start-Process -FilePath "$ProjectRoot\.venv\Scripts\python.exe" `
        -ArgumentList $doctorArgs `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -Wait `
        -PassThru

    if ($process.ExitCode -eq 0) {
        Write-Pass "Doctor check passed"
        $GatesPassed++
    }
    elseif ($process.ExitCode -eq 2) {
        Write-Fail "CRITICAL: Cross-project mismatch detected!"
        Write-Host "       Your credentials point to different Supabase projects." -ForegroundColor Red
        Write-Host "       Fix your .env file before proceeding." -ForegroundColor Red
        $GatesFailed++
        Write-Header "❌ GATE FAILED - DO NOT DEPLOY"
        exit 2
    }
    else {
        Write-Fail "Doctor check failed (exit code: $($process.ExitCode))"
        $GatesFailed++
    }
}
catch {
    Write-Fail "Doctor check error: $_"
    $GatesFailed++
}

# =============================================================================
# GATE 2: Prod Gate (Environment Variables)
# =============================================================================
Write-Step "GATE 2" "Prod Gate (Environment Variables)"

try {
    $prodGateArgs = @("-m", "tools.prod_gate", "--env", $Env)

    $process = Start-Process -FilePath "$ProjectRoot\.venv\Scripts\python.exe" `
        -ArgumentList $prodGateArgs `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -Wait `
        -PassThru

    if ($process.ExitCode -eq 0) {
        Write-Pass "Prod gate passed"
        $GatesPassed++
    }
    else {
        Write-Fail "Prod gate failed (exit code: $($process.ExitCode))"
        $GatesFailed++
    }
}
catch {
    Write-Fail "Prod gate error: $_"
    $GatesFailed++
}

# =============================================================================
# GATE 3: Security Tests
# =============================================================================
if (-not $SkipTests) {
    Write-Step "GATE 3" "Security Tests (Migration Security)"

    try {
        $pytestArgs = @(
            "-m", "pytest",
            "tests/test_migration_security.py",
            "-v",
            "--tb=short"
        )

        $process = Start-Process -FilePath "$ProjectRoot\.venv\Scripts\python.exe" `
            -ArgumentList $pytestArgs `
            -WorkingDirectory $ProjectRoot `
            -NoNewWindow `
            -Wait `
            -PassThru

        if ($process.ExitCode -eq 0) {
            Write-Pass "Security tests passed"
            $GatesPassed++
        }
        else {
            Write-Fail "Security tests failed (exit code: $($process.ExitCode))"
            $GatesFailed++
        }
    }
    catch {
        Write-Fail "Security tests error: $_"
        $GatesFailed++
    }
}
else {
    Write-Info "Skipping security tests (--SkipTests flag)"
}

# =============================================================================
# Summary
# =============================================================================
Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Cyan

$TotalGates = $GatesPassed + $GatesFailed

if ($GatesFailed -eq 0) {
    Write-Host ""
    Write-Host "  ✅ READY FOR DEPLOY" -ForegroundColor Green
    Write-Host ""
    Write-Host "  All $TotalGates gate(s) passed." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Next steps:" -ForegroundColor White
    Write-Host "    1. git push origin main" -ForegroundColor White
    Write-Host "    2. Railway -> API -> Deploy" -ForegroundColor White
    Write-Host "    3. Railway -> Workers -> Deploy (scale to 1)" -ForegroundColor White
    Write-Host "    4. Monitor logs for structured output" -ForegroundColor White
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    exit 0
}
else {
    Write-Host ""
    Write-Host "  ❌ NOT READY FOR DEPLOY" -ForegroundColor Red
    Write-Host ""
    Write-Host "  $GatesFailed of $TotalGates gate(s) failed." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Fix the issues above before deploying." -ForegroundColor Yellow
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    exit 1
}
