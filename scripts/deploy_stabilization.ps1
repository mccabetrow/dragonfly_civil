<#
.SYNOPSIS
    Deploy Final Stabilization - Apply migration and verify system health

.DESCRIPTION
    Orchestrates the production stabilization deployment:
    1. Applies the stabilization migration via db_push.ps1
    2. Runs the stabilize_system.py tool to verify fix
    3. Reports final status

.PARAMETER SupabaseEnv
    Target environment: 'dev' or 'prod' (default: prod)

.PARAMETER SkipMigration
    Skip the migration step (verify only)

.EXAMPLE
    .\scripts\deploy_stabilization.ps1
    # Deploys to prod with full verification

.EXAMPLE
    .\scripts\deploy_stabilization.ps1 -SupabaseEnv dev
    # Deploys to dev environment

.EXAMPLE
    .\scripts\deploy_stabilization.ps1 -SkipMigration
    # Only verify, don't apply migrations
#>

param(
    [ValidateSet("dev", "prod")]
    [string]$SupabaseEnv = "prod",

    [switch]$SkipMigration
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# ═══════════════════════════════════════════════════════════════════════════
# BANNER
# ═══════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  DRAGONFLY STABILIZATION DEPLOYMENT" -ForegroundColor Cyan
Write-Host "  Environment: $($SupabaseEnv.ToUpper())" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════
# LOAD ENVIRONMENT
# ═══════════════════════════════════════════════════════════════════════════

$EnvFile = Join-Path $ProjectRoot ".env.$SupabaseEnv"
if (Test-Path $EnvFile) {
    Write-Host "[INFO] Loading environment from: $EnvFile" -ForegroundColor Gray
    $env:ENV_FILE = $EnvFile
    
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
    
    $env:SUPABASE_MODE = $SupabaseEnv
    Write-Host "[OK] Environment loaded" -ForegroundColor Green
}
else {
    Write-Host "[WARN] Environment file not found: $EnvFile" -ForegroundColor Yellow
    Write-Host "       Proceeding with current environment variables" -ForegroundColor Yellow
}

Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════
# STEP 1: APPLY MIGRATION
# ═══════════════════════════════════════════════════════════════════════════

if (-not $SkipMigration) {
    Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host "  STEP 1: Apply Stabilization Migration" -ForegroundColor White
    Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host ""
    
    $DbPushScript = Join-Path $ScriptDir "db_push.ps1"
    if (-not (Test-Path $DbPushScript)) {
        Write-Host "[ERROR] db_push.ps1 not found at: $DbPushScript" -ForegroundColor Red
        exit 1
    }
    
    try {
        & $DbPushScript -SupabaseEnv $SupabaseEnv
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Migration failed with exit code: $LASTEXITCODE" -ForegroundColor Red
            exit 1
        }
        Write-Host "[OK] Migration applied successfully" -ForegroundColor Green
    }
    catch {
        Write-Host "[ERROR] Migration failed: $_" -ForegroundColor Red
        exit 1
    }
    
    Write-Host ""
}
else {
    Write-Host "[INFO] Skipping migration (--SkipMigration)" -ForegroundColor Gray
    Write-Host ""
}

# ═══════════════════════════════════════════════════════════════════════════
# STEP 2: VERIFY SYSTEM STABILITY
# ═══════════════════════════════════════════════════════════════════════════

Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor White
Write-Host "  STEP 2: Verify System Stability" -ForegroundColor White
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor White
Write-Host ""

$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] Python not found at: $PythonExe" -ForegroundColor Red
    exit 1
}

try {
    & $PythonExe -m tools.stabilize_system --env $SupabaseEnv --verbose
    $StabilizeExitCode = $LASTEXITCODE
}
catch {
    Write-Host "[ERROR] Stabilization check failed: $_" -ForegroundColor Red
    exit 3
}

Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════
# FINAL REPORT
# ═══════════════════════════════════════════════════════════════════════════

Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor White
Write-Host "  DEPLOYMENT SUMMARY" -ForegroundColor White
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor White
Write-Host ""

switch ($StabilizeExitCode) {
    0 {
        Write-Host "  ✅ DEPLOYMENT SUCCESSFUL" -ForegroundColor Green
        Write-Host ""
        Write-Host "  System is stable and all views are accessible." -ForegroundColor Green
        Write-Host "  Dashboard should now load without errors." -ForegroundColor Green
        Write-Host ""
        Write-Host "  Next steps:" -ForegroundColor Gray
        Write-Host "    1. Verify dashboard: https://dragonfly-dashboard.vercel.app" -ForegroundColor Gray
        Write-Host "    2. Run smoke tests: python -m tools.smoke_e2e --env $SupabaseEnv" -ForegroundColor Gray
        Write-Host ""
        exit 0
    }
    1 {
        Write-Host "  ❌ PERMISSION ERRORS" -ForegroundColor Red
        Write-Host ""
        Write-Host "  Some views still have permission issues." -ForegroundColor Red
        Write-Host "  The migration may not have applied correctly." -ForegroundColor Red
        Write-Host ""
        Write-Host "  Debug steps:" -ForegroundColor Yellow
        Write-Host "    1. Check Supabase SQL Editor for errors" -ForegroundColor Yellow
        Write-Host "    2. Run: SELECT * FROM information_schema.table_privileges" -ForegroundColor Yellow
        Write-Host "       WHERE table_name = 'v_enrichment_health';" -ForegroundColor Yellow
        Write-Host ""
        exit 1
    }
    2 {
        Write-Host "  ⚠️  CACHE STUCK" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  PostgREST cache did not reload automatically." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  MANUAL ACTION REQUIRED:" -ForegroundColor Red
        Write-Host "    1. Go to Supabase Dashboard" -ForegroundColor Yellow
        Write-Host "    2. Settings → General → Restart Project" -ForegroundColor Yellow
        Write-Host "    3. Wait 1-2 minutes" -ForegroundColor Yellow
        Write-Host "    4. Re-run: .\scripts\deploy_stabilization.ps1 -SkipMigration" -ForegroundColor Yellow
        Write-Host ""
        exit 2
    }
    default {
        Write-Host "  ❌ SETUP ERROR (Exit code: $StabilizeExitCode)" -ForegroundColor Red
        Write-Host ""
        Write-Host "  Check the error messages above for details." -ForegroundColor Red
        Write-Host ""
        exit $StabilizeExitCode
    }
}
