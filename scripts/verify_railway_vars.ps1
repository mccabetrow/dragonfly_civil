<#
.SYNOPSIS
    Verify Railway environment variables for production deployment safety.

.DESCRIPTION
    This script audits Railway shared and per-service variables to ensure:
    - SUPABASE_DB_URL is set at project level (shared)
    - No service has SUPABASE_DB_URL overrides
    - No service has SUPABASE_MIGRATE_DB_URL (forbidden in runtime)
    - DB URL uses correct pooler format (*.pooler.supabase.com:6543)

.EXAMPLE
    .\scripts\verify_railway_vars.ps1

.NOTES
    Requires: Railway CLI installed and logged in
    Run before any production deployment
#>

param(
    [switch]$Quiet,
    [switch]$Fix  # Future: auto-remove bad overrides
)

$ErrorActionPreference = 'Stop'

Write-Host "`n🔍 Railway Variable Audit" -ForegroundColor Cyan
Write-Host ("=" * 50) -ForegroundColor DarkGray

# Check Railway CLI is available
try {
    $null = Get-Command railway -ErrorAction Stop
}
catch {
    Write-Host "⛔ Railway CLI not found. Install with: winget install Railway.CLI" -ForegroundColor Red
    exit 1
}

# Services to check
$services = @("dragonfly-api", "dragonfly-worker-ingest", "dragonfly-worker-enforcement")
$hasErrors = $false

# ========================================
# Step 1: Check shared variables
# ========================================
Write-Host "`n📦 Checking shared (project-level) variables..." -ForegroundColor Yellow

try {
    $sharedVars = railway variables 2>&1
    $sharedDbUrl = $sharedVars | Select-String "^SUPABASE_DB_URL="
    
    if (-not $sharedDbUrl) {
        Write-Host "⛔ SUPABASE_DB_URL not found in shared variables!" -ForegroundColor Red
        $hasErrors = $true
    }
    else {
        $url = ($sharedDbUrl -replace "SUPABASE_DB_URL=", "").Trim()
        
        # Validate format
        if ($url -notmatch "pooler\.supabase\.com") {
            Write-Host "⛔ URL doesn't use pooler host (must contain 'pooler.supabase.com')" -ForegroundColor Red
            $hasErrors = $true
        }
        elseif ($url -notmatch ":6543") {
            Write-Host "⛔ URL doesn't use pooler port (must contain ':6543')" -ForegroundColor Red
            $hasErrors = $true
        }
        elseif ($url -notmatch "sslmode=require") {
            Write-Host "⛔ URL missing sslmode=require" -ForegroundColor Red
            $hasErrors = $true
        }
        else {
            Write-Host "✅ Shared SUPABASE_DB_URL format validated" -ForegroundColor Green
            if (-not $Quiet) {
                # Mask password for display
                $masked = $url -replace "(postgres\.[^:]+:)[^@]+(@)", '$1***$2'
                Write-Host "   $masked" -ForegroundColor DarkGray
            }
        }
    }
}
catch {
    Write-Host "⛔ Failed to fetch shared variables: $_" -ForegroundColor Red
    $hasErrors = $true
}

# ========================================
# Step 2: Check each service for overrides
# ========================================
Write-Host "`n🔎 Checking service-level overrides..." -ForegroundColor Yellow

foreach ($svc in $services) {
    Write-Host "`n   Service: $svc" -ForegroundColor Cyan
    
    try {
        $svcVars = railway variables -s $svc 2>&1
        
        # Check for SUPABASE_DB_URL override
        $dbOverride = $svcVars | Select-String "^SUPABASE_DB_URL="
        if ($dbOverride) {
            Write-Host "   ⛔ Has SUPABASE_DB_URL override (REMOVE THIS!)" -ForegroundColor Red
            $hasErrors = $true
        }
        else {
            Write-Host "   ✅ No SUPABASE_DB_URL override" -ForegroundColor Green
        }
        
        # Check for forbidden MIGRATE_DB_URL
        $migrateUrl = $svcVars | Select-String "SUPABASE_MIGRATE_DB_URL"
        if ($migrateUrl) {
            Write-Host "   ⛔ Has SUPABASE_MIGRATE_DB_URL (FORBIDDEN in runtime!)" -ForegroundColor Red
            $hasErrors = $true
        }
        else {
            Write-Host "   ✅ No SUPABASE_MIGRATE_DB_URL" -ForegroundColor Green
        }
        
    }
    catch {
        Write-Host "   ⚠️  Failed to check service: $_" -ForegroundColor Yellow
    }
}

# ========================================
# Summary
# ========================================
Write-Host "`n" + ("=" * 50) -ForegroundColor DarkGray

if ($hasErrors) {
    Write-Host "⛔ DEPLOY BLOCKED: Fix the issues above before deploying" -ForegroundColor Red
    Write-Host @"

To fix service overrides:
  railway variables unset SUPABASE_DB_URL -s <service-name>
  railway variables unset SUPABASE_MIGRATE_DB_URL -s <service-name>

To set correct shared variable:
  railway variables set SUPABASE_DB_URL="<pooler-url-from-supabase-dashboard>"
  
  See: docs/ops/PRODUCTION_DB_URL_CONTRACT.md for the required format

"@ -ForegroundColor Yellow
    exit 1
}
else {
    Write-Host "✅ Railway variables validated for production deployment" -ForegroundColor Green
    Write-Host ""
    exit 0
}
