<#
.SYNOPSIS
    Runs AI agent evaluations against the golden dataset.

.DESCRIPTION
    Executes all registered agents against their test cases in the golden dataset.
    Exits with code 1 if any agent's score falls below the threshold (default: 0.95).

    Supports:
    - Multiple agents (ingestion, strategy, etc.)
    - Configurable score threshold
    - JSON output for CI/CD integration
    - Deterministic evaluation (temperature=0 for LLM calls, stubs for now)

.PARAMETER Threshold
    Minimum required score (0.0-1.0). Default: 0.95

.PARAMETER Json
    Output results as JSON instead of human-readable summary.

.PARAMETER Agent
    Run only a specific agent (e.g., 'ingestion', 'strategy').

.PARAMETER Verbose
    Enable verbose logging.

.EXAMPLE
    .\scripts\run_agent_evals.ps1

.EXAMPLE
    .\scripts\run_agent_evals.ps1 -Threshold 0.90

.EXAMPLE
    .\scripts\run_agent_evals.ps1 -Agent strategy -Json

.NOTES
    Author: Dragonfly Engineering
    Date: 2025-12-17
    
    CI Integration:
    - Add to GitHub Actions / Azure Pipelines
    - Exits nonzero if score < threshold
    - Deterministic: agents use stubs or temperature=0
#>

param(
    [Parameter(Mandatory = $false)]
    [ValidateRange(0.0, 1.0)]
    [double]$Threshold = 0.95,

    [Parameter(Mandatory = $false)]
    [switch]$Json,

    [Parameter(Mandatory = $false)]
    [ValidateSet("ingestion", "strategy", "all")]
    [string]$Agent = "all",

    [Parameter(Mandatory = $false)]
    [switch]$ShowDetails
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# =============================================================================
# Banner
# =============================================================================

Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host " Dragonfly Civil - AI Agent Regression Test Harness" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Threshold: $($Threshold.ToString("P0"))" -ForegroundColor Gray
Write-Host "  Agent:     $Agent" -ForegroundColor Gray
Write-Host ""

# =============================================================================
# Locate Python
# =============================================================================

$venvPython = Join-Path $PSScriptRoot "..\\.venv\\Scripts\\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[ERROR] Virtual environment not found at: $venvPython" -ForegroundColor Red
    Write-Host "        Run: python -m venv .venv && .venv\\Scripts\\pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

if ($ShowDetails) {
    Write-Host "[INFO] Using Python: $venvPython" -ForegroundColor Gray
}

# =============================================================================
# Build Python command
# =============================================================================

$pythonArgs = @("-m", "backend.ai.evaluator", "--strict", "--threshold", $Threshold.ToString())

if ($Json) {
    $pythonArgs += "--json"
}

if ($Agent -ne "all") {
    $pythonArgs += "--category"
    $pythonArgs += $Agent
}

# =============================================================================
# Run evaluation
# =============================================================================

Write-Host "[INFO] Running agent evaluations..." -ForegroundColor Gray
Write-Host ""

$startTime = Get-Date

try {
    & $venvPython @pythonArgs
    $exitCode = $LASTEXITCODE
}
catch {
    Write-Host "[ERROR] Failed to run evaluator: $_" -ForegroundColor Red
    exit 1
}

$endTime = Get-Date
$duration = $endTime - $startTime

# =============================================================================
# Report result
# =============================================================================

Write-Host ""
Write-Host "------------------------------------------------------" -ForegroundColor Gray
Write-Host "  Duration: $($duration.TotalSeconds.ToString("F2"))s" -ForegroundColor Gray

if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "[SUCCESS] All agents passed! Score >= $($Threshold.ToString("P0"))" -ForegroundColor Green
    Write-Host ""
}
else {
    Write-Host ""
    Write-Host "[FAILURE] Agent evaluation failed. Score < $($Threshold.ToString("P0"))" -ForegroundColor Red
    Write-Host "          Exit code: $exitCode" -ForegroundColor Red
    Write-Host ""
    Write-Host "  To debug:" -ForegroundColor Yellow
    Write-Host "    .\.venv\Scripts\python.exe -m backend.ai.evaluator --json" -ForegroundColor Yellow
    Write-Host ""
}

exit $exitCode
