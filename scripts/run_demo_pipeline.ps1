<#
.SYNOPSIS
    Golden Path Demo Pipeline Runner

.DESCRIPTION
    Executes the complete Golden Path Demo in under 3 minutes:
    1. Ingest: Generate synthetic CSV and create validated batch
    2. Orchestrate: Process the batch and enqueue downstream jobs
    3. Process: Run workers for a fixed window to drain the queue

.PARAMETER Rows
    Number of synthetic rows to generate (default: 50)

.PARAMETER WorkerDuration
    Seconds to run workers before stopping (default: 60)

.PARAMETER Env
    Supabase environment: dev or prod (default: prod)

.EXAMPLE
    .\scripts\run_demo_pipeline.ps1

.EXAMPLE
    .\scripts\run_demo_pipeline.ps1 -Rows 100 -WorkerDuration 90

.EXAMPLE
    .\scripts\run_demo_pipeline.ps1 -Env dev
#>

[CmdletBinding()]
param(
    [int]$Rows = 50,
    [int]$WorkerDuration = 60,
    [ValidateSet("dev", "prod")]
    [string]$Env = "prod"
)

$ErrorActionPreference = 'Stop'

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

# Banner
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  🐉 DRAGONFLY GOLDEN PATH DEMO                                " -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Environment: $Env" -ForegroundColor Yellow
Write-Host "  Rows:        $Rows" -ForegroundColor Yellow
Write-Host "  Worker Time: ${WorkerDuration}s" -ForegroundColor Yellow
Write-Host ""

# =============================================================================
# STEP 1: INGEST
# =============================================================================

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
Write-Host "📥 STEP 1: Creating Demo Batch..." -ForegroundColor White
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
Write-Host ""

$ingestOutput = & $PythonExe -m tools.demo_ingest --env $Env --rows $Rows 2>&1 | Tee-Object -Variable ingestLog

# Parse batch_id from output
$batchIdLine = $ingestLog | Where-Object { $_ -match "BATCH_ID=" }
if ($batchIdLine) {
    $batchId = ($batchIdLine -split '=')[1].Trim()
    Write-Host ""
    Write-Host "✅ Batch Created: $batchId" -ForegroundColor Green
}
else {
    Write-Host "❌ Failed to create batch" -ForegroundColor Red
    Write-Host $ingestLog
    exit 1
}

# =============================================================================
# STEP 2: ORCHESTRATE
# =============================================================================

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
Write-Host "⏳ STEP 2: Orchestrating Batch..." -ForegroundColor White
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
Write-Host ""

# Run orchestrator once to process the validated batch
$orchestrateOutput = & $PythonExe -m backend.workers.orchestrator --once 2>&1
Write-Host $orchestrateOutput

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✅ Batch Orchestrated - Jobs Enqueued" -ForegroundColor Green
}
else {
    Write-Host ""
    Write-Host "⚠️ Orchestrator returned exit code $LASTEXITCODE" -ForegroundColor Yellow
}

# =============================================================================
# STEP 3: PROCESS JOBS
# =============================================================================

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
Write-Host "🚀 STEP 3: Running Workers (${WorkerDuration}s)..." -ForegroundColor White
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
Write-Host ""

# Check if ingest_processor exists and can run
$processorModule = "backend.workers.ingest_processor"

# Start the worker in background
Write-Host "Starting worker process..." -ForegroundColor Gray

$workerJob = Start-Job -ScriptBlock {
    param($ProjectRoot, $PythonExe, $Env)
    Set-Location $ProjectRoot
    $env:SUPABASE_MODE = $Env
    $env:PYTHONPATH = $ProjectRoot
    & $PythonExe -m backend.workers.ingest_processor 2>&1
} -ArgumentList $ProjectRoot, $PythonExe, $Env

# Show countdown
$startTime = Get-Date
$endTime = $startTime.AddSeconds($WorkerDuration)

while ((Get-Date) -lt $endTime) {
    $remaining = [math]::Ceiling(($endTime - (Get-Date)).TotalSeconds)
    $elapsed = [math]::Floor(((Get-Date) - $startTime).TotalSeconds)
    
    # Progress bar
    $progress = [math]::Min(100, [math]::Floor(($elapsed / $WorkerDuration) * 100))
    $barLength = 40
    $filled = [math]::Floor($barLength * $progress / 100)
    $empty = $barLength - $filled
    $bar = ("█" * $filled) + ("░" * $empty)
    
    Write-Host "`r  [$bar] ${progress}% (${remaining}s remaining)   " -NoNewline -ForegroundColor Cyan
    Start-Sleep -Seconds 1
    
    # Check if job is still running
    if ($workerJob.State -ne 'Running') {
        break
    }
}

Write-Host ""
Write-Host ""

# Stop the worker
Write-Host "Stopping worker..." -ForegroundColor Gray
Stop-Job -Job $workerJob -ErrorAction SilentlyContinue
$workerOutput = Receive-Job -Job $workerJob -ErrorAction SilentlyContinue
Remove-Job -Job $workerJob -Force -ErrorAction SilentlyContinue

# Show worker output (last 10 lines)
if ($workerOutput) {
    Write-Host ""
    Write-Host "Worker Output (last 10 lines):" -ForegroundColor Gray
    $workerOutput | Select-Object -Last 10 | ForEach-Object {
        Write-Host "  $_" -ForegroundColor DarkGray
    }
}

# =============================================================================
# COMPLETE
# =============================================================================

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  ✅ DEMO COMPLETE                                             " -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Batch ID:    $batchId" -ForegroundColor White
Write-Host "  Rows:        $Rows" -ForegroundColor White
Write-Host "  Duration:    ${WorkerDuration}s" -ForegroundColor White
Write-Host "  Environment: $Env" -ForegroundColor White
Write-Host ""
Write-Host "  📊 Check Dashboard for results:" -ForegroundColor Yellow
Write-Host "     https://dragonfly-dashboard.vercel.app" -ForegroundColor Cyan
Write-Host ""
Write-Host "  🔍 Or query directly:" -ForegroundColor Yellow
Write-Host "     SELECT * FROM ops.v_job_queue_summary;" -ForegroundColor DarkGray
Write-Host "     SELECT * FROM intake.simplicity_batches WHERE id = '$batchId';" -ForegroundColor DarkGray
Write-Host ""
