<#
.SYNOPSIS
    Dragonfly Civil - One-Click Dad Demo Automation

.DESCRIPTION
    Master automation script that orchestrates the full demo sequence:
    1. Reset demo state (truncate intake tables)
    2. Open dashboard in browser
    3. Ingest synthetic demo data
    4. Run orchestrator to process batches

.PARAMETER Count
    Number of synthetic rows to generate (default: 50)

.PARAMETER SkipReset
    Skip the database reset step (for re-runs)

.PARAMETER SkipBrowser
    Skip opening the browser

.PARAMETER Env
    Supabase environment: dev or prod (default: dev)

.EXAMPLE
    .\scripts\auto_dad_demo.ps1
    .\scripts\auto_dad_demo.ps1 -Count 100 -SkipReset
#>

param(
    [int]$Count = 50,
    [switch]$SkipReset,
    [switch]$SkipBrowser,
    [ValidateSet("dev", "prod")]
    [string]$Env = "dev"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

$DashboardUrl = "https://dragonfly-dashboard.vercel.app/ops/intake"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

# Set environment
$env:SUPABASE_MODE = $Env
$env:PYTHONPATH = $ProjectRoot

# Source environment loader and status helper
. "$PSScriptRoot\load_env.ps1" -Mode $Env
. "$PSScriptRoot\Write-Status.ps1"

# ═══════════════════════════════════════════════════════════════════════════════
# TERMINAL UI
# ═══════════════════════════════════════════════════════════════════════════════

function Write-Header {
    param([string]$Title)
    Write-Host ""
    Write-Host ("═" * 60) -ForegroundColor DarkGray
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host ("═" * 60) -ForegroundColor DarkGray
    Write-Host ""
}

function Write-Step {
    param([int]$Number, [string]$Message)
    Write-Host "[$Number/5] " -ForegroundColor DarkCyan -NoNewline
    Write-Host $Message -ForegroundColor White
}

function Write-Success {
    param([string]$Message)
    Write-Host "✅ " -ForegroundColor Green -NoNewline
    Write-Host $Message -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "⚠️  " -ForegroundColor Yellow -NoNewline
    Write-Host $Message -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "❌ " -ForegroundColor Red -NoNewline
    Write-Host $Message -ForegroundColor Red
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN SEQUENCE
# ═══════════════════════════════════════════════════════════════════════════════

Write-Header "🚀 Dragonfly Dad Demo - One Click Automation"

Write-Host "Environment: $Env"
Write-Host "Row Count:   $Count"
Write-Host ""

# ───────────────────────────────────────────────────────────────────────────────
# STEP 1: Reset Demo State
# ───────────────────────────────────────────────────────────────────────────────

Write-Step 1 "Reset Demo State"

if ($SkipReset) {
    Write-Warning "Skipping reset (--SkipReset flag)"
}
else {
    try {
        & $PythonExe -m tools.reset_demo_state --force --env $Env
        if ($LASTEXITCODE -ne 0) {
            throw "Reset failed with exit code $LASTEXITCODE"
        }
        Write-Success "Database intake cleared"
    }
    catch {
        Write-Error "Reset failed: $_"
        exit 1
    }
}

Write-Host ""

# ───────────────────────────────────────────────────────────────────────────────
# STEP 2: Open Dashboard
# ───────────────────────────────────────────────────────────────────────────────

Write-Step 2 "Open Dashboard in Browser"

if ($SkipBrowser) {
    Write-Warning "Skipping browser (--SkipBrowser flag)"
}
else {
    try {
        Start-Process $DashboardUrl
        Write-Success "Opened: $DashboardUrl"
    }
    catch {
        Write-Warning "Could not open browser: $_"
    }
}

Write-Host ""

# ───────────────────────────────────────────────────────────────────────────────
# STEP 3: Ingest Demo Data
# ───────────────────────────────────────────────────────────────────────────────

Write-Step 3 "Ingest $Count Synthetic Rows"

try {
    & $PythonExe -m tools.dad_demo_ingest --count $Count --env $Env
    if ($LASTEXITCODE -ne 0) {
        throw "Ingest failed with exit code $LASTEXITCODE"
    }
    Write-Success "Demo data ingested"
}
catch {
    Write-Error "Ingest failed: $_"
    exit 1
}

Write-Host ""

# ───────────────────────────────────────────────────────────────────────────────
# STEP 4: Run Orchestrator
# ───────────────────────────────────────────────────────────────────────────────

Write-Step 4 "Run Orchestrator (Process Batches)"

Write-Host "   Waiting 5 seconds for DB propagation..." -ForegroundColor DarkGray
Start-Sleep -Seconds 5

try {
    & $PythonExe -m backend.workers.orchestrator --once
    if ($LASTEXITCODE -ne 0) {
        throw "Orchestrator failed with exit code $LASTEXITCODE"
    }
    Write-Success "Orchestrator completed"
}
catch {
    Write-Error "Orchestrator failed: $_"
    exit 1
}

Write-Host ""

# ───────────────────────────────────────────────────────────────────────────────
# STEP 5: Process Jobs (10-second burst)
# ───────────────────────────────────────────────────────────────────────────────

Write-Step 5 "Process Jobs (10s burst)"

Write-Host "   Starting processor in background..." -ForegroundColor DarkGray

# Start processor as background job
$processorJob = Start-Job -ScriptBlock {
    param($Root, $PyExe, $EnvMode)
    Set-Location $Root
    $env:SUPABASE_MODE = $EnvMode
    $env:PYTHONPATH = $Root
    & $PyExe -m backend.workers.ingest_processor 2>&1
} -ArgumentList $ProjectRoot, $PythonExe, $Env

# Wait 10 seconds with visual progress
$processorDuration = 10
for ($i = 1; $i -le $processorDuration; $i++) {
    $pct = [math]::Floor(($i / $processorDuration) * 100)
    $bar = ("█" * $i) + ("░" * ($processorDuration - $i))
    Write-Host "`r   [$bar] ${pct}% (${i}s / ${processorDuration}s)    " -NoNewline -ForegroundColor Cyan
    Start-Sleep -Seconds 1
    
    # Exit early if job completed
    if ($processorJob.State -ne 'Running') { break }
}

Write-Host ""
Write-Host ""

# Stop and cleanup
Stop-Job -Job $processorJob -ErrorAction SilentlyContinue
$processorOutput = Receive-Job -Job $processorJob -ErrorAction SilentlyContinue
Remove-Job -Job $processorJob -Force -ErrorAction SilentlyContinue

if ($processorOutput) {
    Write-Host "   Processor output:" -ForegroundColor DarkGray
    $processorOutput | Select-Object -Last 3 | ForEach-Object {
        Write-Host "     $_" -ForegroundColor DarkGray
    }
}

Write-Success "Processor burst completed"

Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════════
# COMPLETE
# ═══════════════════════════════════════════════════════════════════════════════

Write-Header "✅ Demo Sequence Complete"

Write-Host "Summary:" -ForegroundColor White
Write-Host "  • Environment:  $Env" -ForegroundColor Gray
Write-Host "  • Rows Created: $Count" -ForegroundColor Gray
Write-Host "  • Dashboard:    $DashboardUrl" -ForegroundColor Gray
Write-Host ""
Write-Host "Refresh the dashboard to see the new data!" -ForegroundColor Cyan
Write-Host ""

exit 0
