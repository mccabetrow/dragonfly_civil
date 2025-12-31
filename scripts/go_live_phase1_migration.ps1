<#
.SYNOPSIS
    Go-Live Phase 1: Production Migration

.DESCRIPTION
    Applies database migrations to production and validates:
    - db_push.ps1 -SupabaseEnv prod (apply migrations)
    - tools.reload_postgrest --env prod (refresh schema cache)
    - tools.doctor --env prod (validate database health)

    Exits with code 1 on any failure.

.EXAMPLE
    .\go_live_phase1_migration.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'load_env.ps1') -Mode prod | Out-Null
. (Join-Path $PSScriptRoot 'Write-Status.ps1')

$env:SUPABASE_MODE = 'prod'

$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    Write-Status -Level FAIL -Message "Python interpreter not found at $pythonExe"
    exit 1
}

$dbPushScript = Join-Path $PSScriptRoot 'db_push.ps1'
if (-not (Test-Path -LiteralPath $dbPushScript)) {
    Write-Status -Level FAIL -Message "db_push.ps1 not found at $dbPushScript"
    exit 1
}

$powershellExe = Join-Path $PSHOME 'powershell.exe'
if (-not (Test-Path -LiteralPath $powershellExe)) {
    $powershellExe = 'powershell'
}

# ─────────────────────────────────────────────────────────────────────────────
# Step Runner
# ─────────────────────────────────────────────────────────────────────────────
function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][scriptblock]$Action
    )

    Write-Host ""
    Write-Host "→ $Label" -ForegroundColor Cyan
    try {
        $global:LASTEXITCODE = 0
        & $Action
        if ($LASTEXITCODE -ne 0) {
            throw "$Label failed with exit code $LASTEXITCODE"
        }
        Write-Status -Level OK -Message $Label
    }
    catch {
        Write-Status -Level FAIL -Message $Label
        Write-Host $_.Exception.Message -ForegroundColor Red
        exit 1
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 Steps
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
Write-Host "  PHASE 1: MIGRATION (Prod)" -ForegroundColor Yellow
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
Write-Host ""
Write-Host "  ⚠️  WARNING: This will modify the PRODUCTION database!" -ForegroundColor Red
Write-Host ""

Invoke-Step "db_push (prod)" {
    & $powershellExe -NoProfile -ExecutionPolicy Bypass -File $dbPushScript -SupabaseEnv prod
}

Invoke-Step "tools.reload_postgrest (prod)" {
    & $pythonExe -m tools.reload_postgrest --env prod
}

Invoke-Step "tools.doctor (prod)" {
    & $pythonExe -m tools.doctor --env prod
}

# ─────────────────────────────────────────────────────────────────────────────
# Success
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  PHASE 1: MIGRATION COMPLETE" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Green

exit 0
