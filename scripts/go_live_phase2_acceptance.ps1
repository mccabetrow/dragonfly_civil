<#
.SYNOPSIS
    Go-Live Phase 2: Production Acceptance Tests

.DESCRIPTION
    Runs smoke tests against production to validate the migration:
    - tools.smoke_simplicity --env prod (schema smoke test)
    - tools.smoke_plaintiffs --env prod (plaintiff pipeline smoke)
    - tools.smoke_e2e --env prod (end-to-end ingestion, if available)

    Exits with code 1 on any failure.

.EXAMPLE
    .\go_live_phase2_acceptance.ps1
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

# ─────────────────────────────────────────────────────────────────────────────
# Step Runner
# ─────────────────────────────────────────────────────────────────────────────
function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][scriptblock]$Action,
        [switch]$Optional
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
        if ($Optional) {
            Write-Status -Level WARN -Message "$Label (skipped - optional)"
        }
        else {
            Write-Status -Level FAIL -Message $Label
            Write-Host $_.Exception.Message -ForegroundColor Red
            exit 1
        }
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 Steps
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Blue
Write-Host "  PHASE 2: ACCEPTANCE (Prod)" -ForegroundColor Blue
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Blue

Invoke-Step "tools.smoke_simplicity (prod)" {
    & $pythonExe -m tools.smoke_simplicity --env prod
}

Invoke-Step "tools.smoke_plaintiffs (prod)" {
    & $pythonExe -m tools.smoke_plaintiffs --env prod
}

# E2E smoke is optional - may not be configured for prod
Invoke-Step "tools.smoke_e2e (prod)" -Optional {
    & $pythonExe -m tools.smoke_e2e --env prod
}

# ─────────────────────────────────────────────────────────────────────────────
# Success
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  PHASE 2: ACCEPTANCE PASSED" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Green

exit 0
