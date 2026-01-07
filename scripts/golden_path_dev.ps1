<#
.SYNOPSIS
    Runs the Golden Path End-to-End validation against DEV environment.

.DESCRIPTION
    This is the "Green Light" test that validates the entire Dragonfly pipeline:
    Ingest -> Process -> Score

    State Persistence:
        After a successful run, batch info is saved to .golden_path_last.json
        Use -Cleanup to remove test data from the last run.

.EXAMPLE
    .\scripts\golden_path_dev.ps1
    # Run full golden path validation

.EXAMPLE
    .\scripts\golden_path_dev.ps1 -Cleanup
    # Remove test data from the last run (reads .golden_path_last.json)

.EXAMPLE
    .\scripts\golden_path_dev.ps1 -CleanupAll
    # Remove ALL golden path test data (legacy heuristic cleanup)

.NOTES
    Exit Codes:
        0 - Golden Path PASSED / Cleanup succeeded
        1 - Golden Path FAILED / Cleanup failed
#>

param(
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
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "            GOLDEN PATH - DEV ENVIRONMENT                        " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host ""

# Load environment
$env:SUPABASE_MODE = "dev"
$env:DRAGONFLY_ENV = "dev"

# Source .env.dev if exists
$EnvFile = Join-Path $ProjectRoot ".env.dev"
if (Test-Path $EnvFile) {
    Write-Host "Loading environment from .env.dev..." -ForegroundColor Gray
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

$PythonArgs = @("-m", "tools.golden_path", "--env", "dev")
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
        Write-Host "  [DONE] DEV CLEANUP COMPLETE                                    " -ForegroundColor Green
        Write-Host "=================================================================" -ForegroundColor Green
    }
    else {
        Write-Host "=================================================================" -ForegroundColor Red
        Write-Host "  [FAIL] DEV CLEANUP FAILED                                      " -ForegroundColor Red
        Write-Host "=================================================================" -ForegroundColor Red
    }
}
elseif ($ExitCode -eq 0) {
    Write-Host "=================================================================" -ForegroundColor Green
    Write-Host "  [PASS] DEV GOLDEN PATH PASSED - GREEN LIGHT                    " -ForegroundColor Green
    Write-Host "=================================================================" -ForegroundColor Green
}
else {
    Write-Host "=================================================================" -ForegroundColor Red
    Write-Host "  [FAIL] DEV GOLDEN PATH FAILED - NO GO                          " -ForegroundColor Red
    Write-Host "=================================================================" -ForegroundColor Red
}

exit $ExitCode
