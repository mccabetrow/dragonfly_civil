<#
.SYNOPSIS
    Dragonfly Golden Path Pre-Flight Verification Script
    Orchestrates all pre-deployment checks for "No Surprises" deployments.

.DESCRIPTION
    This script runs the complete pre-flight verification sequence:
    1. python -m tools.doctor --env $EnvMode
    2. pytest tests/test_raw_sql_guard.py
    3. pytest tests/test_migration_security.py  
    4. python -m tools.prod_gate --env $EnvMode
    
    ALL checks must pass for deployment to proceed.

.PARAMETER EnvMode
    Target environment: 'dev' or 'prod'

.EXAMPLE
    .\verify_preflight.ps1 -EnvMode dev
    .\verify_preflight.ps1 -EnvMode prod
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev", "prod")]
    [string]$EnvMode
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# =============================================================================
# Configuration
# =============================================================================
$script:WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$script:PythonExe = Join-Path $WorkspaceRoot ".venv" "Scripts" "python.exe"
$script:GatesPassed = 0
$script:GatesFailed = 0
$script:TotalGates = 4

# =============================================================================
# Helper Functions
# =============================================================================
function Write-Gate {
    param(
        [int]$Number,
        [string]$Name,
        [string]$Status
    )
    
    if ($Status -eq "PASS") {
        Write-Host "[GATE $Number] " -NoNewline -ForegroundColor Cyan
        Write-Host "PASS: " -NoNewline -ForegroundColor Green
        Write-Host $Name
    } elseif ($Status -eq "FAIL") {
        Write-Host "[GATE $Number] " -NoNewline -ForegroundColor Cyan
        Write-Host "FAIL: " -NoNewline -ForegroundColor Red
        Write-Host $Name
    } elseif ($Status -eq "RUNNING") {
        Write-Host "[GATE $Number] " -NoNewline -ForegroundColor Cyan
        Write-Host "RUNNING: " -NoNewline -ForegroundColor Yellow
        Write-Host $Name
    } else {
        Write-Host "[GATE $Number] $Status $Name" -ForegroundColor White
    }
}

function Write-Header {
    param([string]$Message)
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor DarkGray
    Write-Host "  $Message" -ForegroundColor White
    Write-Host ("=" * 70) -ForegroundColor DarkGray
    Write-Host ""
}

function Write-Summary {
    param(
        [bool]$AllPassed,
        [string]$EnvMode
    )
    
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor DarkGray
    
    if ($AllPassed) {
        Write-Host "  [PASS] $EnvMode READY FOR DEPLOY" -ForegroundColor Green
        Write-Host ""
        Write-Host "  All $script:TotalGates gates passed. You may proceed with deployment." -ForegroundColor White
    } else {
        Write-Host "  [FAIL] ABORT - $script:GatesFailed of $script:TotalGates gates failed" -ForegroundColor Red
        Write-Host ""
        Write-Host "  Fix the failing checks before deployment." -ForegroundColor Yellow
    }
    
    Write-Host ("=" * 70) -ForegroundColor DarkGray
    Write-Host ""
}

# =============================================================================
# Gate Functions
# =============================================================================

function Test-Gate1-Doctor {
    Write-Gate -Number 1 -Name "Doctor Diagnostic (tools.doctor)" -Status "RUNNING"
    
    $env:SUPABASE_MODE = $EnvMode
    
    try {
        & $script:PythonExe -m tools.doctor --env $EnvMode
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -eq 0) {
            Write-Gate -Number 1 -Name "Doctor Diagnostic" -Status "PASS"
            $script:GatesPassed++
            return $true
        } else {
            Write-Gate -Number 1 -Name "Doctor Diagnostic (exit code: $exitCode)" -Status "FAIL"
            $script:GatesFailed++
            return $false
        }
    }
    catch {
        Write-Gate -Number 1 -Name "Doctor Diagnostic (exception: $_)" -Status "FAIL"
        $script:GatesFailed++
        return $false
    }
}

function Test-Gate2-RawSQLGuard {
    Write-Gate -Number 2 -Name "Raw SQL Guard (test_raw_sql_guard.py)" -Status "RUNNING"
    
    $testFile = Join-Path $WorkspaceRoot "tests" "test_raw_sql_guard.py"
    
    if (-not (Test-Path $testFile)) {
        Write-Host "    Warning: Test file not found: $testFile" -ForegroundColor Yellow
        Write-Gate -Number 2 -Name "Raw SQL Guard (test file missing)" -Status "FAIL"
        $script:GatesFailed++
        return $false
    }
    
    try {
        & $script:PythonExe -m pytest $testFile -v --tb=short
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -eq 0) {
            Write-Gate -Number 2 -Name "Raw SQL Guard" -Status "PASS"
            $script:GatesPassed++
            return $true
        } else {
            Write-Gate -Number 2 -Name "Raw SQL Guard (pytest exit: $exitCode)" -Status "FAIL"
            $script:GatesFailed++
            return $false
        }
    }
    catch {
        Write-Gate -Number 2 -Name "Raw SQL Guard (exception: $_)" -Status "FAIL"
        $script:GatesFailed++
        return $false
    }
}

function Test-Gate3-MigrationSecurity {
    Write-Gate -Number 3 -Name "Migration Security (test_migration_security.py)" -Status "RUNNING"
    
    $testFile = Join-Path $WorkspaceRoot "tests" "test_migration_security.py"
    
    if (-not (Test-Path $testFile)) {
        Write-Host "    Warning: Test file not found: $testFile" -ForegroundColor Yellow
        Write-Gate -Number 3 -Name "Migration Security (test file missing)" -Status "FAIL"
        $script:GatesFailed++
        return $false
    }
    
    try {
        & $script:PythonExe -m pytest $testFile -v --tb=short
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -eq 0) {
            Write-Gate -Number 3 -Name "Migration Security" -Status "PASS"
            $script:GatesPassed++
            return $true
        } else {
            Write-Gate -Number 3 -Name "Migration Security (pytest exit: $exitCode)" -Status "FAIL"
            $script:GatesFailed++
            return $false
        }
    }
    catch {
        Write-Gate -Number 3 -Name "Migration Security (exception: $_)" -Status "FAIL"
        $script:GatesFailed++
        return $false
    }
}

function Test-Gate4-ProdGate {
    Write-Gate -Number 4 -Name "Prod Gate (tools.prod_gate)" -Status "RUNNING"
    
    $env:SUPABASE_MODE = $EnvMode
    
    try {
        & $script:PythonExe -m tools.prod_gate --env $EnvMode
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -eq 0) {
            Write-Gate -Number 4 -Name "Prod Gate" -Status "PASS"
            $script:GatesPassed++
            return $true
        } else {
            Write-Gate -Number 4 -Name "Prod Gate (exit code: $exitCode)" -Status "FAIL"
            $script:GatesFailed++
            return $false
        }
    }
    catch {
        Write-Gate -Number 4 -Name "Prod Gate (exception: $_)" -Status "FAIL"
        $script:GatesFailed++
        return $false
    }
}

# =============================================================================
# Main Execution
# =============================================================================

Write-Header "DRAGONFLY GOLDEN PATH PRE-FLIGHT - $($EnvMode.ToUpper())"

# Verify Python exists
if (-not (Test-Path $script:PythonExe)) {
    Write-Host "ERROR: Python not found at $script:PythonExe" -ForegroundColor Red
    Write-Host "Please run: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

Write-Host "Environment: $EnvMode" -ForegroundColor Cyan
Write-Host "Workspace:   $WorkspaceRoot" -ForegroundColor Cyan
Write-Host "Python:      $script:PythonExe" -ForegroundColor Cyan
Write-Host ""

# Set environment variable
$env:SUPABASE_MODE = $EnvMode

# Run all gates in sequence (stop on critical failure optional)
$gate1 = Test-Gate1-Doctor
Write-Host ""

$gate2 = Test-Gate2-RawSQLGuard
Write-Host ""

$gate3 = Test-Gate3-MigrationSecurity
Write-Host ""

$gate4 = Test-Gate4-ProdGate

# Final Summary
$allPassed = ($script:GatesFailed -eq 0)
Write-Summary -AllPassed $allPassed -EnvMode $EnvMode.ToUpper()

# Exit with appropriate code
if ($allPassed) {
    exit 0
} else {
    exit 1
}
