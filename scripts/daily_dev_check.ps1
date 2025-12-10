<#
.SYNOPSIS
    Daily dev health check script for Dragonfly Civil.

.DESCRIPTION
    Runs migrations, tests, and doctor checks against the specified environment.
    Use this as your daily "one-click" routine before development.

.PARAMETER SupabaseEnv
    Target environment: 'dev' or 'prod'. Defaults to 'dev'.

.EXAMPLE
    .\scripts\daily_dev_check.ps1
    .\scripts\daily_dev_check.ps1 -SupabaseEnv dev
#>

param(
    [ValidateSet('dev', 'prod')]
    [string]$SupabaseEnv = "dev"
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot\..

Write-Host "=== 🐉 Dragonfly Dev Health Check ===" -ForegroundColor Green
Write-Host "Environment: $SupabaseEnv" -ForegroundColor Cyan
$env:SUPABASE_MODE = $SupabaseEnv

# Step 1: Apply migrations
Write-Host "`n[1/3] Applying migrations..." -ForegroundColor Yellow
try {
    & .\scripts\db_migrate.ps1 -SupabaseEnv $SupabaseEnv
    Write-Host "  ✓ Migrations applied" -ForegroundColor Green
}
catch {
    Write-Host "  ✗ Migration failed: $_" -ForegroundColor Red
    exit 1
}

# Step 2: Run critical tests
Write-Host "`n[2/3] Running tests..." -ForegroundColor Yellow
try {
    & .\.venv\Scripts\python.exe -m pytest `
        tests/test_workers_ingest.py `
        tests/test_workers_enforcement.py `
        tests/test_analytics_intake_radar.py `
        -q --tb=short
    Write-Host "  ✓ Tests passed" -ForegroundColor Green
}
catch {
    Write-Host "  ✗ Tests failed: $_" -ForegroundColor Red
    exit 1
}

# Step 3: System doctor
Write-Host "`n[3/3] System Doctor..." -ForegroundColor Yellow
try {
    & .\.venv\Scripts\python.exe -m tools.doctor --env $SupabaseEnv
    Write-Host "  ✓ Doctor checks passed" -ForegroundColor Green
}
catch {
    Write-Host "  ✗ Doctor checks failed: $_" -ForegroundColor Red
    exit 1
}

Write-Host "`n✅ Ready to Build." -ForegroundColor Green
