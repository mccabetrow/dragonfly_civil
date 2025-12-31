<#
.SYNOPSIS
    Go-Live Phase 0: Preflight Checks (Dev Environment)

.DESCRIPTION
    Validates the system is ready for production migration by running:
    - tools.doctor (database health)
    - tools.smoke_simplicity (schema smoke test)
    - tools.smoke_plaintiffs (plaintiff pipeline smoke)
    - tools.pgrst_reload (PostgREST schema cache)
    - npm run build (frontend compilation)

    Exits with code 1 on any failure.

.EXAMPLE
    .\go_live_phase0_preflight.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'load_env.ps1') -Mode dev | Out-Null
. (Join-Path $PSScriptRoot 'Write-Status.ps1')

$env:SUPABASE_MODE = 'dev'

$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    Write-Status -Level FAIL -Message "Python interpreter not found at $pythonExe"
    exit 1
}

$dashboardDir = Join-Path $repoRoot 'dragonfly-dashboard'
if (-not (Test-Path -LiteralPath $dashboardDir)) {
    Write-Status -Level FAIL -Message "Dashboard directory not found at $dashboardDir"
    exit 1
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
# Phase 0 Steps
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Magenta
Write-Host "  PHASE 0: PREFLIGHT (Dev)" -ForegroundColor Magenta
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Magenta

Invoke-Step "tools.doctor (dev)" {
    & $pythonExe -m tools.doctor --env dev
}

Invoke-Step "tools.smoke_simplicity (dev)" {
    & $pythonExe -m tools.smoke_simplicity --env dev
}

Invoke-Step "tools.smoke_plaintiffs (dev)" {
    & $pythonExe -m tools.smoke_plaintiffs --env dev
}

Invoke-Step "tools.pgrst_reload (dev)" {
    & $pythonExe -m tools.pgrst_reload
}

Invoke-Step "npm run build (dashboard)" {
    Push-Location $dashboardDir
    try {
        cmd /c "npm install --silent" 2>&1 | Out-Null
        cmd /c "npm run build"
    }
    finally {
        Pop-Location
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# Success
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  PHASE 0: PREFLIGHT PASSED" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Green

exit 0
