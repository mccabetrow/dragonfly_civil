<#
.SYNOPSIS
    Post-schema deployment hook - reloads PostgREST schema cache.

.DESCRIPTION
    This script is designed to be run after database migrations are applied.
    It forces PostgREST to reload its schema cache, ensuring the API
    immediately recognizes new views, tables, and columns.

    Use this to eliminate PGRST002 "Could not find..." errors after deployments.

.PARAMETER Env
    Target environment: 'dev' or 'prod'. Defaults to current SUPABASE_MODE.

.EXAMPLE
    # Run after migrations
    .\scripts\deploy_hook_post_schema.ps1

.EXAMPLE
    # Explicit environment
    .\scripts\deploy_hook_post_schema.ps1 -Env prod

.NOTES
    This script calls: python -m tools.reload_postgrest
    Requires: psycopg3, src.supabase_client
#>

param(
    [ValidateSet('dev', 'prod')]
    [string]$Env = $null
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot\..

# ─────────────────────────────────────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  🔄 Post-Schema Deployment Hook                                                " -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Environment Resolution
# ─────────────────────────────────────────────────────────────────────────────
if (-not $Env) {
    $Env = if ($env:SUPABASE_MODE) { $env:SUPABASE_MODE } else { 'dev' }
}

Write-Host "  Environment: $Env" -ForegroundColor Yellow
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Load environment file
# ─────────────────────────────────────────────────────────────────────────────
$envFile = ".env.$Env"
if (Test-Path $envFile) {
    Write-Host "  Loading: $envFile" -ForegroundColor DarkGray
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            [Environment]::SetEnvironmentVariable($key, $value, 'Process')
        }
    }
}
else {
    Write-Host "  ⚠️  No $envFile found, using existing environment" -ForegroundColor Yellow
}

# Ensure SUPABASE_MODE is set
$env:SUPABASE_MODE = $Env

# ─────────────────────────────────────────────────────────────────────────────
# Execute PostgREST Reload
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Executing: python -m tools.reload_postgrest --env $Env" -ForegroundColor DarkGray
Write-Host ""

try {
    & .\.venv\Scripts\python.exe -m tools.reload_postgrest --env $Env
    $exitCode = $LASTEXITCODE
}
catch {
    Write-Host "  ❌ Python execution failed: $_" -ForegroundColor Red
    exit 1
}

# ─────────────────────────────────────────────────────────────────────────────
# Result
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Green
    Write-Host "  ✅ Schema cache reloaded - PGRST002 errors should be fixed                   " -ForegroundColor Green
    Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Green
}
else {
    Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Red
    Write-Host "  ❌ Schema reload failed - check database connectivity                        " -ForegroundColor Red
    Write-Host "═══════════════════════════════════════════════════════════════════════════════" -ForegroundColor Red
    exit $exitCode
}
