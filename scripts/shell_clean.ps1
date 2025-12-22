<#
.SYNOPSIS
    Clean Shell Launcher - Guarantees pristine environment for Dev or Prod.

.DESCRIPTION
    This script is the authoritative entry point for Dragonfly Civil development.
    It aggressively purges stale environment variables to prevent Dev/Prod
    cross-contamination, then loads the correct environment and verifies it.

.PARAMETER Mode
    The target environment: 'dev' or 'prod'.

.EXAMPLE
    .\scripts\shell_clean.ps1 -Mode dev
    .\scripts\shell_clean.ps1 -Mode prod
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('dev', 'prod')]
    [string]$Mode
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ============================================================================
# STEP 1: THE PURGE
# ============================================================================
# Aggressively remove ALL environment variables that could cause contamination

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " CLEAN SHELL: Purging stale environment variables..." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$purgedCount = 0
$prefixes = @('SUPABASE_', 'DRAGONFLY_')

foreach ($prefix in $prefixes) {
    $varsToRemove = Get-ChildItem Env: | Where-Object { $_.Name -like "$prefix*" }
    foreach ($var in $varsToRemove) {
        Write-Host "  [PURGE] $($var.Name)" -ForegroundColor DarkGray
        Remove-Item "Env:\$($var.Name)" -ErrorAction SilentlyContinue
        $purgedCount++
    }
}

if ($purgedCount -eq 0) {
    Write-Host "  (No stale variables found)" -ForegroundColor DarkGray
}
else {
    Write-Host "  Purged $purgedCount variable(s)" -ForegroundColor Yellow
}

# ============================================================================
# STEP 2: THE LOAD
# ============================================================================
# Load the correct environment using the canonical loader

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " CLEAN SHELL: Loading $($Mode.ToUpper()) environment..." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$loaderScript = Join-Path $PSScriptRoot 'load_env.ps1'
if (-not (Test-Path $loaderScript)) {
    Write-Host "  [ERROR] load_env.ps1 not found at: $loaderScript" -ForegroundColor Red
    exit 1
}

# Source the loader script
& $loaderScript -Mode $Mode

# ============================================================================
# STEP 3: THE VERIFICATION
# ============================================================================
# Run the environment doctor to verify correctness

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " CLEAN SHELL: Running environment doctor..." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$pythonExe = Join-Path $PSScriptRoot '..\\.venv\\Scripts\\python.exe'
if (-not (Test-Path $pythonExe)) {
    # Fallback to system python
    $pythonExe = 'python'
}

try {
    & $pythonExe -m tools.env_doctor
    $doctorExitCode = $LASTEXITCODE
}
catch {
    Write-Host "  [WARN] env_doctor failed: $_" -ForegroundColor Yellow
    $doctorExitCode = 1
}

# ============================================================================
# STEP 4: THE REPORT
# ============================================================================
# Print summary header with key environment details

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " === [ $($Mode.ToUpper()) ] SHELL ACTIVE ===" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green

# Parse project ref from SUPABASE_URL
$supabaseUrl = $env:SUPABASE_URL
if ($supabaseUrl) {
    if ($supabaseUrl -match 'https://([a-z0-9]+)\.supabase\.co') {
        $projectRef = $Matches[1]
        Write-Host "  Project Ref:    $projectRef" -ForegroundColor White
    }
    else {
        Write-Host "  Project Ref:    (could not parse)" -ForegroundColor Yellow
    }
}
else {
    Write-Host "  Project Ref:    [NOT SET]" -ForegroundColor Red
}

# Parse connection mode from SUPABASE_DB_URL
$dbUrl = $env:SUPABASE_DB_URL
if ($dbUrl) {
    if ($dbUrl -match ':(\d+)/') {
        $port = $Matches[1]
        if ($port -eq '5432') {
            $connMode = 'Direct (5432)'
        }
        elseif ($port -eq '6543') {
            $connMode = 'Pooler - Transaction (6543)'
        }
        elseif ($port -eq '5433') {
            $connMode = 'Pooler - Session (5433)'
        }
        else {
            $connMode = "Custom Port ($port)"
        }
        Write-Host "  DB Connection:  $connMode" -ForegroundColor White
    }
    else {
        Write-Host "  DB Connection:  (could not parse port)" -ForegroundColor Yellow
    }
}
else {
    Write-Host "  DB Connection:  [NOT SET]" -ForegroundColor Red
}

# Show SUPABASE_MODE
Write-Host "  SUPABASE_MODE:  $env:SUPABASE_MODE" -ForegroundColor White

Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

# Return doctor exit code for CI/automation
if ($doctorExitCode -ne 0) {
    Write-Host "[WARN] Environment doctor reported issues. Review above." -ForegroundColor Yellow
}

exit $doctorExitCode
