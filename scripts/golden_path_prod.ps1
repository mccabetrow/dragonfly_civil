<#
.SYNOPSIS
    Runs the Golden Path End-to-End validation against PROD environment.

.DESCRIPTION
    This is the "Green Light" test that validates the entire Dragonfly pipeline:
    Ingest -> Process -> Score

    WARNING: This creates test records in PRODUCTION (tagged with GOLD- prefix).

    State Persistence:
        After a successful run, batch info is saved to .golden_path_last.json
        Use -Cleanup to remove test data from the last run.

.EXAMPLE
    .\scripts\golden_path_prod.ps1
    # Run full golden path validation (prompts for confirmation)

.EXAMPLE
    .\scripts\golden_path_prod.ps1 -Force
    # Skip confirmation prompt

.EXAMPLE
    .\scripts\golden_path_prod.ps1 -Cleanup
    # Remove test data from the last run (reads .golden_path_last.json)

.EXAMPLE
    .\scripts\golden_path_prod.ps1 -CleanupAll -Force
    # Remove ALL golden path test data (legacy heuristic cleanup)

.NOTES
    Exit Codes:
        0 - Golden Path PASSED / Cleanup succeeded
        1 - Golden Path FAILED / Cleanup failed
#>

param(
    [switch]$Force,
    [switch]$Json,
    [switch]$Cleanup,
    [switch]$CleanupAll,
    [string]$BatchId
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Navigate to project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Yellow
Write-Host "            GOLDEN PATH - PROD ENVIRONMENT                       " -ForegroundColor Yellow
Write-Host "=================================================================" -ForegroundColor Yellow
Write-Host ""

# Safety confirmation
if (-not $Force) {
    if ($Cleanup -or $CleanupAll) {
        Write-Host "This will DELETE test records from PRODUCTION." -ForegroundColor Yellow
    }
    else {
        Write-Host "This will CREATE test records in PRODUCTION." -ForegroundColor Yellow
        Write-Host "The records will be tagged with 'GOLD-' prefix for easy identification." -ForegroundColor Gray
    }
    Write-Host ""
    $Confirm = Read-Host "Type 'PROD' to confirm"
    if ($Confirm -ne "PROD") {
        Write-Host "Aborted." -ForegroundColor Red
        exit 1
    }
}

# Load environment
$env:SUPABASE_MODE = "prod"
$env:DRAGONFLY_ENV = "prod"

# Source .env.prod if exists
$EnvFile = Join-Path $ProjectRoot ".env.prod"
if (Test-Path $EnvFile) {
    Write-Host "Loading environment from .env.prod..." -ForegroundColor Gray
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line -split "=", 2
            $key = $parts[0].Trim()
            $value = $parts[1].Trim().Trim('"').Trim("'")
            if (-not [Environment]::GetEnvironmentVariable($key)) {
                [Environment]::SetEnvironmentVariable($key, $value)
            }
        }
    }
}

# Build command
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonPath)) {
    Write-Host "ERROR: Python venv not found at $PythonPath" -ForegroundColor Red
    exit 1
}

$PythonArgs = @("-m", "tools.golden_path", "--env", "prod", "--strict")
if ($Json) {
    $PythonArgs += "--json"
}
if ($Cleanup) {
    $PythonArgs += "--cleanup"
}
if ($CleanupAll) {
    $PythonArgs += "--cleanup-all"
}
if ($BatchId) {
    $PythonArgs += @("--batch-id", $BatchId)
}

# Run golden path
Write-Host ""
& $PythonPath $PythonArgs
$ExitCode = $LASTEXITCODE

Write-Host ""
if ($Cleanup -or $CleanupAll) {
    if ($ExitCode -eq 0) {
        Write-Host "=================================================================" -ForegroundColor Green
        Write-Host "  [DONE] PROD CLEANUP COMPLETE                                   " -ForegroundColor Green
        Write-Host "=================================================================" -ForegroundColor Green
    }
    else {
        Write-Host "=================================================================" -ForegroundColor Red
        Write-Host "  [FAIL] PROD CLEANUP FAILED                                     " -ForegroundColor Red
        Write-Host "=================================================================" -ForegroundColor Red
    }
}
elseif ($ExitCode -eq 0) {
    Write-Host "=================================================================" -ForegroundColor Green
    Write-Host "  [PASS] PROD GOLDEN PATH PASSED - GREEN LIGHT                   " -ForegroundColor Green
    Write-Host "=================================================================" -ForegroundColor Green
}
else {
    Write-Host "=================================================================" -ForegroundColor Red
    Write-Host "  [FAIL] PROD GOLDEN PATH FAILED - NO GO                         " -ForegroundColor Red
    Write-Host "=================================================================" -ForegroundColor Red
}

exit $ExitCode
