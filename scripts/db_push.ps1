<#
.SYNOPSIS
    Apply Supabase migrations to dev or prod database.

.DESCRIPTION
    Robust PowerShell script to apply migrations safely:
    - Validates Supabase CLI is installed
    - Prompts for confirmation in production
    - Delegates to db_migrate.ps1 for actual migration work
    - Provides clear success/failure output

.PARAMETER SupabaseEnv
    Target environment: 'dev' or 'prod'. Required.

.PARAMETER Force
    Skip confirmation prompt for production (used by Release Train).

.EXAMPLE
    .\scripts\db_push.ps1 -SupabaseEnv dev
    .\scripts\db_push.ps1 -SupabaseEnv prod
    .\scripts\db_push.ps1 -SupabaseEnv prod -Force
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev", "prod")]
    [string]$SupabaseEnv,

    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# ----------------------------------------------------------------------------
# PRE-FLIGHT CHECKS
# ----------------------------------------------------------------------------

Write-Host "`n=== Dragonfly Database Migration ===" -ForegroundColor Cyan
if ($SupabaseEnv -eq 'prod') {
    Write-Host "Target: $SupabaseEnv" -ForegroundColor Red
}
else {
    Write-Host "Target: $SupabaseEnv" -ForegroundColor Green
}

# Check Supabase CLI is installed
$SupabaseCli = $null

# Try known location first
$knownPath = "$env:LOCALAPPDATA\Programs\supabase\supabase.exe"
if (Test-Path $knownPath) {
    $SupabaseCli = $knownPath
}

# Fall back to PATH
if (-not $SupabaseCli) {
    $found = Get-Command supabase -ErrorAction SilentlyContinue
    if ($found) {
        $SupabaseCli = $found.Source
    }
}

if (-not $SupabaseCli) {
    Write-Host "[ERROR] Supabase CLI not found!" -ForegroundColor Red
    Write-Host "        Install with: winget install Supabase.CLI" -ForegroundColor Yellow
    exit 1
}

Write-Host "[OK] Supabase CLI found: $SupabaseCli" -ForegroundColor Green

# ----------------------------------------------------------------------------
# PRODUCTION CONFIRMATION GATE
# ----------------------------------------------------------------------------

if ($SupabaseEnv -eq 'prod' -and -not $Force) {
    Write-Host ""
    Write-Host "[WARNING] You are about to apply migrations to PRODUCTION!" -ForegroundColor Red
    Write-Host "          This is a destructive operation that cannot be undone." -ForegroundColor Yellow
    Write-Host ""
    $confirm = Read-Host "Type 'YES' to proceed (or anything else to abort)"
    if ($confirm -ne 'YES') {
        Write-Host "[ABORTED] User cancelled production deployment." -ForegroundColor Yellow
        exit 0
    }
    Write-Host "[OK] Production deployment confirmed." -ForegroundColor Green
}

# ----------------------------------------------------------------------------
# SET ENVIRONMENT
# ----------------------------------------------------------------------------

$env:SUPABASE_MODE = $SupabaseEnv

# ----------------------------------------------------------------------------
# DELEGATE TO CANONICAL MIGRATION SCRIPT
# ----------------------------------------------------------------------------

$migrateScript = Join-Path $PSScriptRoot "db_migrate.ps1"
if (-not (Test-Path $migrateScript)) {
    Write-Host "[ERROR] db_migrate.ps1 not found at: $migrateScript" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Applying migrations..." -ForegroundColor Cyan

if ($Force) {
    & $migrateScript -SupabaseEnv $SupabaseEnv -Force
}
else {
    & $migrateScript -SupabaseEnv $SupabaseEnv
}

$exitCode = $LASTEXITCODE
if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "[OK] Database Migrations Applied to $SupabaseEnv" -ForegroundColor Green
}
else {
    Write-Host ""
    Write-Host "[ERROR] Migration failed with exit code $exitCode" -ForegroundColor Red
    exit $exitCode
}
