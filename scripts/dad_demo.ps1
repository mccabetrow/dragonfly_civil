<#
.SYNOPSIS
    Dragonfly "Dad Demo" - The Showrunner Script

.DESCRIPTION
    A professional, fail-safe demonstration script for non-technical audiences.
    Orchestrates the complete pipeline (Ingest -> Orchestrate -> Process) with
    visual, impressive terminal output.

    Steps:
    1. Environment Setup (load_env.ps1)
    2. Health Check (doctor_all --tolerant)
    3. Ingest Demo Data (dad_demo_ingest --count 50)
    4. Orchestrate Batch (orchestrator --once)
    5. Process Jobs (processor for 10s, then clean stop)
    6. Completion Banner

.PARAMETER Env
    Supabase environment: dev or prod (default: prod)

.PARAMETER Count
    Number of synthetic rows to generate (default: 50)

.PARAMETER SkipDoctor
    Skip the health check step for faster demo

.EXAMPLE
    .\scripts\dad_demo.ps1

.EXAMPLE
    .\scripts\dad_demo.ps1 -Env dev -Count 100

.EXAMPLE
    .\scripts\dad_demo.ps1 -SkipDoctor
#>

[CmdletBinding()]
param(
    [ValidateSet("dev", "prod")]
    [string]$Env = "prod",
    
    [int]$Count = 50,
    
    [switch]$SkipDoctor
)

$ErrorActionPreference = 'Stop'

# =============================================================================
# SETUP
# =============================================================================

# Navigate to project root
$ProjectRoot = Join-Path $PSScriptRoot '..'
Set-Location -Path $ProjectRoot

# Activate virtual environment
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    & .\.venv\Scripts\Activate.ps1
}

$env:PYTHONPATH = (Get-Location).Path
$env:SUPABASE_MODE = $Env

$PythonExe = ".\.venv\Scripts\python.exe"

# Load environment variables
. "$PSScriptRoot\load_env.ps1" -Mode $Env

# Load status helper (for consistent output)
. "$PSScriptRoot\Write-Status.ps1"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

function Write-Banner {
    param([string]$Title, [string]$Color = "Cyan")
    Write-Host ""
    Write-Host ("=" * 65) -ForegroundColor $Color
    Write-Host "  $Title" -ForegroundColor $Color
    Write-Host ("=" * 65) -ForegroundColor $Color
    Write-Host ""
}

function Write-Step {
    param([int]$Number, [string]$Title)
    Write-Host ""
    Write-Host ("-" * 65) -ForegroundColor Gray
    Write-Host "  STEP $Number`: $Title" -ForegroundColor White
    Write-Host ("-" * 65) -ForegroundColor Gray
    Write-Host ""
}

function Write-Success {
    param([string]$Message)
    Write-Status -Level OK -Message $Message
}

function Write-Warning {
    param([string]$Message)
    Write-Status -Level WARN -Message $Message
}

function Write-Fail {
    param([string]$Message)
    Write-Status -Level FAIL -Message $Message
}

# =============================================================================
# MAIN DEMO
# =============================================================================

Write-Banner "DRAGONFLY DAD DEMO" "Cyan"

Write-Host "  Environment:    $Env" -ForegroundColor Yellow
Write-Host "  Synthetic Rows: $Count" -ForegroundColor Yellow
Write-Host "  Skip Doctor:    $SkipDoctor" -ForegroundColor Yellow
Write-Host ""

$startTime = Get-Date

# -----------------------------------------------------------------------------
# STEP 1: Health Check (optional)
# -----------------------------------------------------------------------------

if (-not $SkipDoctor) {
    Write-Step -Number 1 -Title "Health Check (doctor_all --tolerant)"
    
    # Temporarily suppress stderr output from Python logging
    $prevErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    
    $doctorOutput = & $PythonExe -m tools.doctor_all --env $Env --tolerant 2>&1
    $doctorExitCode = $LASTEXITCODE
    
    $ErrorActionPreference = $prevErrorAction
    
    # Show last few lines of output (filter out stderr formatting)
    $doctorOutput | Where-Object { $_ -is [string] -or $_.ToString() -notmatch '^python\.exe :' } | Select-Object -Last 5 | ForEach-Object {
        $line = if ($_ -is [string]) { $_ } else { $_.ToString() }
        Write-Host "  $line" -ForegroundColor DarkGray
    }
    
    if ($doctorExitCode -eq 0) {
        Write-Success "System health verified"
    }
    else {
        Write-Warning "Health check had warnings (continuing in tolerant mode)"
    }
}
else {
    Write-Host "[SKIP] Health check skipped" -ForegroundColor DarkGray
}

# -----------------------------------------------------------------------------
# STEP 2: Ingest Demo Data
# -----------------------------------------------------------------------------

Write-Step -Number 2 -Title "Ingesting Synthetic Judgments"

$ingestOutput = & $PythonExe -m tools.dad_demo_ingest --env $Env --count $Count 2>&1

# Display output
$ingestOutput | ForEach-Object {
    Write-Host "  $_" -ForegroundColor Gray
}

# Parse batch_id from output
$batchIdLine = $ingestOutput | Where-Object { $_ -match "BATCH_ID=" }
if ($batchIdLine) {
    $batchId = ($batchIdLine -split '=')[1].Trim()
    Write-Success "Batch created: $batchId"
}
else {
    Write-Fail "Failed to create batch"
    exit 1
}

# -----------------------------------------------------------------------------
# STEP 3: Orchestrate Batch
# -----------------------------------------------------------------------------

Write-Step -Number 3 -Title "Orchestrating Batch (enqueue jobs)"

$orchestrateOutput = & $PythonExe -m backend.workers.orchestrator --once 2>&1
$orchestrateExitCode = $LASTEXITCODE

# Show output
$orchestrateOutput | Select-Object -Last 5 | ForEach-Object {
    Write-Host "  $_" -ForegroundColor DarkGray
}

if ($orchestrateExitCode -eq 0) {
    Write-Success "Batch orchestrated - jobs enqueued"
}
else {
    Write-Warning "Orchestrator returned code $orchestrateExitCode"
}

# -----------------------------------------------------------------------------
# STEP 4: Process Jobs (10 second burst)
# -----------------------------------------------------------------------------

Write-Step -Number 4 -Title "Processing Jobs (10s burst)"

Write-Host "  Starting processor in background..." -ForegroundColor Gray

# Start processor in background
$processorJob = Start-Job -ScriptBlock {
    param($ProjectRoot, $PythonExe, $Env)
    Set-Location $ProjectRoot
    $env:SUPABASE_MODE = $Env
    $env:PYTHONPATH = $ProjectRoot
    & $PythonExe -m backend.workers.ingest_processor 2>&1
} -ArgumentList $ProjectRoot, $PythonExe, $Env

# Visual countdown
$processorDuration = 10
$endTime = (Get-Date).AddSeconds($processorDuration)

while ((Get-Date) -lt $endTime) {
    $remaining = [math]::Ceiling(($endTime - (Get-Date)).TotalSeconds)
    $elapsed = $processorDuration - $remaining
    
    # Progress bar
    $progress = [math]::Min(100, [math]::Floor(($elapsed / $processorDuration) * 100))
    $barLength = 40
    $filled = [math]::Floor($barLength * $progress / 100)
    $empty = $barLength - $filled
    $bar = ("█" * $filled) + ("░" * $empty)
    
    Write-Host "`r  [$bar] ${progress}% (${remaining}s remaining)   " -NoNewline -ForegroundColor Cyan
    Start-Sleep -Milliseconds 500
    
    # Check if job completed early
    if ($processorJob.State -ne 'Running') {
        break
    }
}

Write-Host ""
Write-Host ""

# Clean stop
Write-Host "  Stopping processor..." -ForegroundColor Gray
Stop-Job -Job $processorJob -ErrorAction SilentlyContinue
$processorOutput = Receive-Job -Job $processorJob -ErrorAction SilentlyContinue
Remove-Job -Job $processorJob -Force -ErrorAction SilentlyContinue

# Show processor output (last 3 lines)
if ($processorOutput) {
    Write-Host ""
    Write-Host "  Processor output:" -ForegroundColor DarkGray
    $processorOutput | Select-Object -Last 3 | ForEach-Object {
        Write-Host "    $_" -ForegroundColor DarkGray
    }
}

Write-Success "Processor completed (10s burst)"

# =============================================================================
# COMPLETION
# =============================================================================

$elapsed = (Get-Date) - $startTime

Write-Banner "DEMO COMPLETE" "Green"

Write-Host "  Batch ID:    $batchId" -ForegroundColor White
Write-Host "  Rows:        $Count" -ForegroundColor White
Write-Host "  Duration:    $([math]::Round($elapsed.TotalSeconds, 1))s" -ForegroundColor White
Write-Host "  Environment: $Env" -ForegroundColor White
Write-Host ""
Write-Host "  " -NoNewline
Write-Status -Level OK -Message "REFRESH DASHBOARD TO SEE RESULTS"
Write-Host ""
Write-Host "  Dashboard: https://dragonfly-dashboard.vercel.app" -ForegroundColor Cyan
Write-Host ""
Write-Host ("=" * 65) -ForegroundColor Green
Write-Host ""
