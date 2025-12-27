<#
.SYNOPSIS
    Deploy workers to Railway and verify they're alive.

.DESCRIPTION
    This script handles the complete worker deployment lifecycle:
    1. Deploys workers to Railway (detached)
    2. Waits for initial boot time
    3. Verifies workers are heartbeating
    4. Reports success or failure

.PARAMETER Service
    The Railway service name (default: dragonfly-workers)

.PARAMETER Timeout
    Timeout in seconds for worker verification (default: 90)

.PARAMETER MinWorkers
    Minimum number of workers expected (default: 1)

.PARAMETER SkipDeploy
    Skip the Railway deploy step (just verify existing workers)

.PARAMETER Verbose
    Show detailed output during verification

.EXAMPLE
    .\scripts\deploy_workers.ps1
    
.EXAMPLE
    .\scripts\deploy_workers.ps1 -Timeout 120 -MinWorkers 2

.EXAMPLE
    .\scripts\deploy_workers.ps1 -SkipDeploy  # Just verify existing workers
#>

param(
    [string]$Service = "dragonfly-workers",
    [int]$Timeout = 90,
    [int]$MinWorkers = 1,
    [switch]$SkipDeploy,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptRoot

# =============================================================================
# HEADER
# =============================================================================

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  WORKER DEPLOYMENT - $Service" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# =============================================================================
# STEP 1: LOAD ENVIRONMENT
# =============================================================================

Write-Host "[ENV] Loading environment..." -ForegroundColor Yellow

$envFile = Join-Path $projectRoot ".env.prod"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^([^#=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
    Write-Host "  Loaded .env.prod" -ForegroundColor Green
}
else {
    Write-Host "  ⚠️  .env.prod not found, using existing environment" -ForegroundColor Yellow
}

# =============================================================================
# STEP 2: DEPLOY TO RAILWAY (unless SkipDeploy)
# =============================================================================

if (-not $SkipDeploy) {
    Write-Host ""
    Write-Host "[DEPLOY] Deploying $Service to Railway..." -ForegroundColor Yellow
    
    # Check if Railway CLI is available
    $railwayPath = Get-Command "railway" -ErrorAction SilentlyContinue
    if (-not $railwayPath) {
        Write-Host "  ❌ Railway CLI not found. Install with: npm install -g @railway/cli" -ForegroundColor Red
        exit 1
    }

    try {
        # Deploy in detached mode (don't wait for completion)
        $deployOutput = & railway up --service $Service --detach 2>&1
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ❌ Railway deploy failed:" -ForegroundColor Red
            Write-Host $deployOutput -ForegroundColor Red
            exit 1
        }
        
        Write-Host "  ✅ Deploy triggered successfully" -ForegroundColor Green
        Write-Host ""
        
        # Wait for initial boot
        Write-Host "[BOOT] Waiting for workers to boot..." -ForegroundColor Yellow
        Write-Host "  ⏳ Sleeping 15s for container startup..." -ForegroundColor Gray
        Start-Sleep -Seconds 15
        
    }
    catch {
        Write-Host "  ❌ Deploy error: $_" -ForegroundColor Red
        exit 1
    }
}
else {
    Write-Host "[SKIP] Skipping deploy step (-SkipDeploy flag set)" -ForegroundColor Yellow
}

# =============================================================================
# STEP 3: VERIFY WORKER HEARTBEATS
# =============================================================================

Write-Host ""
Write-Host "[VERIFY] Checking worker heartbeats..." -ForegroundColor Yellow

$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    $pythonPath = "python"
}

$verifyArgs = @(
    "-m", "tools.verify_worker_startup",
    "--mode", "prod",
    "--timeout", $Timeout,
    "--min-workers", $MinWorkers
)

if ($Verbose) {
    $verifyArgs += "--verbose"
}

try {
    & $pythonPath $verifyArgs
    $verifyExitCode = $LASTEXITCODE
}
catch {
    Write-Host "  ❌ Verification script error: $_" -ForegroundColor Red
    $verifyExitCode = 1
}

# =============================================================================
# STEP 4: REPORT RESULT
# =============================================================================

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan

if ($verifyExitCode -eq 0) {
    Write-Host "  🚀 WORKERS DEPLOYED & VERIFIED" -ForegroundColor Green
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Workers are alive and heartbeating." -ForegroundColor Green
    Write-Host "  The deployment is complete." -ForegroundColor Green
    Write-Host ""
    exit 0
}
else {
    Write-Host "  ⚠️  DEPLOYMENT TRIGGERED, BUT WORKERS ARE SILENT" -ForegroundColor Yellow
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  The Railway deploy was triggered, but workers are not heartbeating." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Next Steps:" -ForegroundColor Yellow
    Write-Host "    1. Check Railway logs: railway logs --service $Service" -ForegroundColor Gray
    Write-Host "    2. Verify environment variables are set in Railway" -ForegroundColor Gray
    Write-Host "    3. Check for Python/dependency errors" -ForegroundColor Gray
    Write-Host ""
    exit 1
}
