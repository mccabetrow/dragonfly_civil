<#
.SYNOPSIS
    Go-Live Master Director - Orchestrates the complete go-live sequence.

.DESCRIPTION
    Executes the Dragonfly Go-Live procedure with strict ordering, error checking,
    and human confirmation gates:

    Phase 0: Preflight (dev) - Validates system readiness
    Gate 1:  Human confirmation to proceed with prod migration
    Phase 1: Migration (prod) - Applies database migrations
    Gate 2:  Human confirmation to proceed with acceptance tests
    Phase 2: Acceptance (prod) - Validates production deployment

    Exits immediately on any failure. Human gates require explicit 'y' to proceed.

.PARAMETER NonInteractive
    Skip confirmation gates (for CI/CD pipelines). USE WITH EXTREME CAUTION.

.EXAMPLE
    .\go_live_master.ps1

.EXAMPLE
    .\go_live_master.ps1 -NonInteractive  # CI mode - no prompts
#>

[CmdletBinding()]
param(
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────
$scriptRoot = $PSScriptRoot
. (Join-Path $scriptRoot 'Write-Status.ps1')

$phase0Script = Join-Path $scriptRoot 'go_live_phase0_preflight.ps1'
$phase1Script = Join-Path $scriptRoot 'go_live_phase1_migration.ps1'
$phase2Script = Join-Path $scriptRoot 'go_live_phase2_acceptance.ps1'

foreach ($script in @($phase0Script, $phase1Script, $phase2Script)) {
    if (-not (Test-Path -LiteralPath $script)) {
        Write-Status -Level FAIL -Message "Required script not found: $script"
        exit 1
    }
}

$powershellExe = Join-Path $PSHOME 'powershell.exe'
if (-not (Test-Path -LiteralPath $powershellExe)) {
    $powershellExe = 'powershell'
}

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
function Invoke-Phase {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string]$ScriptPath
    )

    Write-Host ""
    Write-Host "Starting: $Label" -ForegroundColor Cyan
    Write-Host "Script:   $ScriptPath" -ForegroundColor DarkGray
    Write-Host ""

    $global:LASTEXITCODE = 0
    & $powershellExe -NoProfile -ExecutionPolicy Bypass -File $ScriptPath

    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Status -Level FAIL -Message "$Label failed with exit code $LASTEXITCODE"
        Write-Host ""
        Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Red
        Write-Host "  GO-LIVE ABORTED" -ForegroundColor Red
        Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Red
        exit 1
    }
}

function Request-Confirmation {
    param(
        [Parameter(Mandatory)][string]$Message
    )

    if ($NonInteractive) {
        Write-Host ""
        Write-Status -Level WARN -Message "Non-interactive mode: auto-proceeding"
        return
    }

    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
    Write-Host "  CONFIRMATION GATE" -ForegroundColor Yellow
    Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  $Message" -ForegroundColor White
    Write-Host ""

    $response = Read-Host "  Type 'y' to continue, any other key to abort"

    if ($response -ne 'y') {
        Write-Host ""
        Write-Status -Level WARN -Message "User aborted at confirmation gate"
        Write-Host ""
        Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
        Write-Host "  GO-LIVE CANCELLED BY USER" -ForegroundColor Yellow
        Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
        exit 0
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────
Clear-Host
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "              DRAGONFLY CIVIL - GO-LIVE SEQUENCE                   " -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "  This script will execute the complete go-live procedure:" -ForegroundColor White
Write-Host ""
Write-Host "    Phase 0: Preflight checks (dev environment)" -ForegroundColor Gray
Write-Host "    Phase 1: Database migration (PRODUCTION)" -ForegroundColor Gray
Write-Host "    Phase 2: Acceptance tests (PRODUCTION)" -ForegroundColor Gray
Write-Host ""
Write-Host "  Each phase requires the previous to pass." -ForegroundColor White
Write-Host "  Human confirmation is required before modifying production." -ForegroundColor White
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Cyan

if (-not $NonInteractive) {
    Write-Host ""
    $startConfirm = Read-Host "  Press ENTER to begin, or Ctrl+C to abort"
}

# ─────────────────────────────────────────────────────────────────────────────
# Phase 0: Preflight
# ─────────────────────────────────────────────────────────────────────────────
Invoke-Phase -Label "PHASE 0: PREFLIGHT" -ScriptPath $phase0Script

# ─────────────────────────────────────────────────────────────────────────────
# Gate 1: Confirm Production Migration
# ─────────────────────────────────────────────────────────────────────────────
Request-Confirmation -Message "Preflight PASSED. Ready to migrate PRODUCTION database? [y/N]"

# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: Migration
# ─────────────────────────────────────────────────────────────────────────────
Invoke-Phase -Label "PHASE 1: MIGRATION" -ScriptPath $phase1Script

# ─────────────────────────────────────────────────────────────────────────────
# Gate 2: Confirm Acceptance Tests
# ─────────────────────────────────────────────────────────────────────────────
Request-Confirmation -Message "Migration COMPLETE. Ready to run production smoke tests? [y/N]"

# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: Acceptance
# ─────────────────────────────────────────────────────────────────────────────
Invoke-Phase -Label "PHASE 2: ACCEPTANCE" -ScriptPath $phase2Script

# ─────────────────────────────────────────────────────────────────────────────
# Success
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "                                                                   " -ForegroundColor Green
Write-Host "                    SYSTEM IS LIVE                                 " -ForegroundColor Green
Write-Host "                                                                   " -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  All phases completed successfully." -ForegroundColor White
Write-Host "  Production database is migrated and validated." -ForegroundColor White
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Yellow
Write-Host "    1. Monitor Sentinel: python -m backend.workers.sentinel --json" -ForegroundColor Gray
Write-Host "    2. Check dashboard: https://dragonfly-dashboard.vercel.app" -ForegroundColor Gray
Write-Host "    3. Review Supabase logs for any warnings" -ForegroundColor Gray
Write-Host ""

exit 0
