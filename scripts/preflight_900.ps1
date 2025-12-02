<#
.SYNOPSIS
Safety gate for the 900-plaintiff import - validates schema, enrichment, and tests.

.DESCRIPTION
Runs a targeted preflight before importing the 900-plaintiff cohort. This script
ensures the environment is in a safe state by checking:

  1. tools.check_schema_consistency - validates that all critical views, tables,
     and RPCs exist and match the expected schema.
  2. scripts/check_prod_schema.py  - confirms the live schema matches the frozen
     snapshot (drift detection).
  3. tools.enrichment_smoke        - end-to-end test: insert -> enqueue -> enrich
     -> verify (proves the core_judgments trigger + handler work).
  4. pytest tests/test_judgment_enrich_handler.py - runs idempotency and handler
     unit tests to ensure retry safety.

Each step exits non-zero on failure, halting the preflight immediately.

USAGE:
    .\scripts\preflight_900.ps1                  # default: dev
    .\scripts\preflight_900.ps1 -SupabaseEnv dev
    .\scripts\preflight_900.ps1 -SupabaseEnv prod -SkipPytest

.PARAMETER SupabaseEnv
    Supabase environment to target (dev or prod). Defaults to dev.

.PARAMETER SkipPytest
    Skip the pytest step (for faster iteration when only checking live schema).

.EXAMPLE
    .\scripts\preflight_900.ps1 -SupabaseEnv dev

.NOTES
    Author: dragonfly-db-guardian
    Requires: Python venv at .venv, load_env.ps1 for credentials
#>

[CmdletBinding()]
param(
    [ValidateSet('dev', 'prod')]
    [string]$SupabaseEnv = 'dev',

    [switch]$SkipPytest
)

$ErrorActionPreference = 'Stop'

# ------------------------------------------------------------------------------
# Resolve paths
# ------------------------------------------------------------------------------

$repoRoot = Split-Path -Parent $PSScriptRoot
$envLoader = Join-Path $PSScriptRoot 'load_env.ps1'

if (Test-Path -LiteralPath $envLoader) {
    . $envLoader | Out-Null
}

$env:SUPABASE_MODE = $SupabaseEnv

$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    Write-Host "[FAIL] Python interpreter not found at $pythonExe. Run scripts/bootstrap.ps1 first." -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------------------------
# Invoke-Step helper (mirrors preflight_dev.ps1 pattern)
# ------------------------------------------------------------------------------

function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][scriptblock]$Action
    )

    Write-Host ""
    Write-Host ">> $Label" -ForegroundColor Cyan
    try {
        $global:LASTEXITCODE = 0
        & $Action
        if ($LASTEXITCODE -ne 0) {
            throw "$Label failed with exit code $LASTEXITCODE"
        }
        Write-Host "[OK] $Label" -ForegroundColor Green
    }
    catch {
        Write-Host "[FAIL] $Label" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
        throw
    }
}

# ------------------------------------------------------------------------------
# Preflight steps
# ------------------------------------------------------------------------------

Write-Host "======================================================" -ForegroundColor Yellow
Write-Host "  Preflight 900: Safety gate for $SupabaseEnv import  " -ForegroundColor Yellow
Write-Host "======================================================" -ForegroundColor Yellow

Invoke-Step "tools.check_schema_consistency ($SupabaseEnv)" {
    & $pythonExe -m tools.check_schema_consistency --env $SupabaseEnv
}

Invoke-Step "scripts/check_prod_schema.py ($SupabaseEnv)" {
    & $pythonExe 'scripts/check_prod_schema.py' --env $SupabaseEnv
}

Invoke-Step "tools.enrichment_smoke ($SupabaseEnv)" {
    & $pythonExe -m tools.enrichment_smoke --env $SupabaseEnv
}

if (-not $SkipPytest) {
    Invoke-Step "pytest tests/test_judgment_enrich_handler.py" {
        & $pythonExe -m pytest tests/test_judgment_enrich_handler.py -q
    }
}
else {
    Write-Host ""
    Write-Host ">> pytest skipped (--SkipPytest)" -ForegroundColor DarkGray
}

# ------------------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------------------

Write-Host ""
Write-Host "======================================================" -ForegroundColor Green
Write-Host "[OK] Preflight 900 complete - SAFE TO RUN 900 IMPORT" -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Environment:  $SupabaseEnv" -ForegroundColor White
Write-Host "Steps run:" -ForegroundColor White
Write-Host "  1. check_schema_consistency  - critical views/tables/RPCs exist" -ForegroundColor Gray
Write-Host "  2. check_prod_schema         - live schema matches frozen snapshot" -ForegroundColor Gray
Write-Host "  3. enrichment_smoke          - core_judgments -> enrich flow works" -ForegroundColor Gray
if (-not $SkipPytest) {
    Write-Host "  4. pytest                    - idempotency + handler tests pass" -ForegroundColor Gray
}
Write-Host ""
Write-Host "You may now run:" -ForegroundColor Cyan
Write-Host "  python -m tools.dry_run_900 --env $SupabaseEnv --count 900 --reset" -ForegroundColor White
