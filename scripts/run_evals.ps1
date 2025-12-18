<#
.SYNOPSIS
    Runs the Dragonfly Golden Dataset Evaluator.

.DESCRIPTION
    Executes the AI/ML regression test suite against the golden dataset.
    Returns exit code 1 if any test fails (strict mode enforced).

.EXAMPLE
    .\scripts\run_evals.ps1

.EXAMPLE
    .\scripts\run_evals.ps1 -Category ingestion

.EXAMPLE
    .\scripts\run_evals.ps1 -Json

.NOTES
    Author: Dragonfly Engineering
    Date: 2025-12-17
#>

param(
    [Parameter(Mandatory = $false)]
    [ValidateSet("ingestion", "strategy")]
    [string]$Category,

    [Parameter(Mandatory = $false)]
    [switch]$Json,

    [Parameter(Mandatory = $false)]
    [switch]$NoStrict
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Banner
Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " Dragonfly Civil - Golden Dataset Evaluator" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# Locate Python
$venvPython = Join-Path $PSScriptRoot "..\\.venv\\Scripts\\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[ERROR] Virtual environment not found at: $venvPython" -ForegroundColor Red
    Write-Host "        Run: python -m venv .venv && .venv\\Scripts\\pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

Write-Host "[INFO] Using Python: $venvPython" -ForegroundColor Gray

# Build command arguments
$pythonArgs = @("-m", "backend.ai.evaluator")

# Always use strict mode unless -NoStrict is specified
if (-not $NoStrict) {
    $pythonArgs += "--strict"
}

if ($Json) {
    $pythonArgs += "--json"
}

if ($Category) {
    $pythonArgs += "--category"
    $pythonArgs += $Category
}

# Run the evaluator
Write-Host "[INFO] Running evaluator..." -ForegroundColor Gray
Write-Host ""

try {
    & $venvPython @pythonArgs
    $exitCode = $LASTEXITCODE
}
catch {
    Write-Host "[ERROR] Failed to run evaluator: $_" -ForegroundColor Red
    exit 1
}

# Report result
Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "[SUCCESS] All golden dataset tests passed!" -ForegroundColor Green
}
else {
    Write-Host "[FAILURE] Some golden dataset tests failed. Exit code: $exitCode" -ForegroundColor Red
}

exit $exitCode
