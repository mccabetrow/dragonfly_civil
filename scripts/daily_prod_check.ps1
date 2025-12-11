<#
.SYNOPSIS
    Daily prod health check script for Dragonfly Civil.

.DESCRIPTION
    Runs migrations and smoke tests against production.
    Use this to verify prod is healthy before demos or deployments.

.EXAMPLE
    .\scripts\daily_prod_check.ps1
#>

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot\..

Write-Host "=== [DRAGONFLY] PROD Status ===" -ForegroundColor Red
Write-Host "[!] Running against PRODUCTION" -ForegroundColor Yellow
$env:SUPABASE_MODE = 'prod'

# Step 1: Sync schema (apply any pending migrations)
Write-Host "`n[1/2] Syncing Schema..." -ForegroundColor Yellow
try {
    & .\scripts\db_migrate.ps1 -SupabaseEnv prod
    Write-Host "  [OK] Schema synced" -ForegroundColor Green
}
catch {
    Write-Host "  [FAIL] Schema sync failed: $_" -ForegroundColor Red
    exit 1
}

# Step 2: Run prod smoke test
Write-Host "`n[2/2] Checking Pulse..." -ForegroundColor Yellow
try {
    # Check if prod_smoke exists, otherwise use doctor
    $prodSmokeExists = Test-Path ".\tools\prod_smoke.py"
    if ($prodSmokeExists) {
        & .\.venv\Scripts\python.exe -m tools.prod_smoke
    }
    else {
        Write-Host "  (Using doctor as prod_smoke not found)" -ForegroundColor DarkGray
        & .\.venv\Scripts\python.exe -m tools.doctor
    }
    Write-Host "  [OK] Prod health check passed" -ForegroundColor Green
}
catch {
    Write-Host "  [FAIL] Prod health check failed: $_" -ForegroundColor Red
    exit 1
}

Write-Host "`n>>> PROD IS HEALTHY. <<<" -ForegroundColor Green
