<#
.SYNOPSIS
    Intake Pipeline Smoke Test Wrapper

.DESCRIPTION
    Runs the golden smoke test for the intake pipeline.
    This script is called by gate_preflight.ps1 Phase 2 (Functional Tests).

.EXAMPLE
    .\scripts\smoke_intake.ps1
    .\scripts\smoke_intake.ps1 -Verbose
    .\scripts\smoke_intake.ps1 -CleanupOnly

.OUTPUTS
    Exit 0 = All tests passed
    Exit 1 = Tests failed

.NOTES
    Part of Dragonfly Civil intake hardening (Phase B)
#>

[CmdletBinding()]
param(
    [switch]$ShowDetails,
    [switch]$CleanupOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --------------------------------------------------------------------------
# Environment Setup
# --------------------------------------------------------------------------
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot

try {
    # Load environment variables
    if (Test-Path "./scripts/load_env.ps1") {
        . ./scripts/load_env.ps1
    }

    $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $python)) {
        Write-Error "Python venv not found at $python"
        exit 1
    }

    Write-Host ""
    Write-Host "==============================================================" -ForegroundColor Cyan
    Write-Host "             INTAKE PIPELINE SMOKE TEST                       " -ForegroundColor Cyan
    Write-Host "==============================================================" -ForegroundColor Cyan
    Write-Host ""

    # Build arguments
    $pyArgs = @("-m", "tools.smoke_intake")

    if ($ShowDetails) {
        $pyArgs += "--verbose"
    }

    if ($CleanupOnly) {
        $pyArgs += "--cleanup-only"
    }

    # Run the smoke test
    & $python @pyArgs
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Write-Host ""
        Write-Host "[OK] Intake smoke test completed successfully" -ForegroundColor Green
    }
    else {
        Write-Host ""
        Write-Host "[FAIL] Intake smoke test failed" -ForegroundColor Red
    }

    exit $exitCode

}
catch {
    Write-Host ""
    Write-Host "[ERROR] Intake smoke test error: $_" -ForegroundColor Red
    exit 1

}
finally {
    Pop-Location
}
