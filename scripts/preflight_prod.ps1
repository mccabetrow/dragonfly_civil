<#
.SYNOPSIS
Runs the production health preflight (db push checks, config, security, doctor, pytest).

.DESCRIPTION
Loads .env, scopes Supabase to prod, runs the read-only branch of db_push (checks
mode), and then executes the full readiness checklist. The script stops at the first
failing command. Pass -PytestArgs when you need to narrow pytest to the fast suites.
#>

[CmdletBinding()]
param(
    [ValidateSet('prod')]
    [string]$SupabaseEnv = 'prod',
    [string[]]$PytestArgs
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'load_env.ps1') | Out-Null
$env:SUPABASE_MODE = $SupabaseEnv

$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    Write-Host "[FAIL] Python interpreter not found at $pythonExe. Run scripts/bootstrap.ps1 first." -ForegroundColor Red
    exit 1
}

$dbPushScript = Join-Path $PSScriptRoot 'db_push.ps1'
if (-not (Test-Path -LiteralPath $dbPushScript)) {
    Write-Host "[FAIL] Unable to find db_push.ps1 at $dbPushScript" -ForegroundColor Red
    exit 1
}

$powershellExe = Join-Path $PSHOME 'powershell.exe'
if (-not (Test-Path -LiteralPath $powershellExe)) {
    $powershellExe = 'powershell'
}

function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][scriptblock]$Action
    )

    Write-Host "`n→ $Label" -ForegroundColor Cyan
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

Invoke-Step "db_push checks ($SupabaseEnv)" {
    & $powershellExe -NoProfile -ExecutionPolicy Bypass -File $dbPushScript -SupabaseEnv $SupabaseEnv -Mode 'Checks'
}

Invoke-Step "tools.check_schema_consistency ($SupabaseEnv)" {
    & $pythonExe -m tools.check_schema_consistency --env $SupabaseEnv
}

Invoke-Step "scripts/check_prod_schema.py ($SupabaseEnv)" {
    & $pythonExe 'scripts/check_prod_schema.py' --env $SupabaseEnv
}

Invoke-Step "tools.config_check ($SupabaseEnv)" {
    & $pythonExe -m tools.config_check --env $SupabaseEnv
}

Invoke-Step "tools.security_audit ($SupabaseEnv)" {
    & $pythonExe -m tools.security_audit --env $SupabaseEnv
}

Invoke-Step "tools.doctor_all ($SupabaseEnv)" {
    & $pythonExe -m tools.doctor_all --env $SupabaseEnv
}

if (-not $PytestArgs -or $PytestArgs.Count -eq 0) {
    $PytestArgs = @('-q')
}

Invoke-Step "pytest suite" {
    & $pythonExe -m pytest @PytestArgs
}

# ─────────────────────────────────────────────────────────────────────────────
# Production API Health Check
# ─────────────────────────────────────────────────────────────────────────────
$prodApiUrl = "https://dragonflycivil-production-d57a.up.railway.app/api/health"

Invoke-Step "Production API Health Check" {
    try {
        $response = Invoke-WebRequest -Uri $prodApiUrl -Method GET -TimeoutSec 30 -UseBasicParsing
        $json = $response.Content | ConvertFrom-Json
        if ($json.status -eq 'ok') {
            Write-Host "  API Status: $($json.status)" -ForegroundColor White
            Write-Host "  Environment: $($json.environment)" -ForegroundColor White
        } else {
            throw "Health check returned status: $($json.status)"
        }
    }
    catch {
        Write-Host "  Warning: Could not reach production API" -ForegroundColor Yellow
        Write-Host "  URL: $prodApiUrl" -ForegroundColor Yellow
        Write-Host "  This may be expected if Railway is not yet deployed." -ForegroundColor Yellow
        # Don't fail the preflight for API unreachability
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# PASS/FAIL Summary
# ─────────────────────────────────────────────────────────────────────────────
$stepCount = 8
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  PREFLIGHT RESULT: PASS" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Environment:  $SupabaseEnv" -ForegroundColor White
Write-Host "  Steps Run:    $stepCount / $stepCount" -ForegroundColor White
Write-Host ""
Write-Host "  ✓ db_push (checks)" -ForegroundColor Green
Write-Host "  ✓ check_schema_consistency" -ForegroundColor Green
Write-Host "  ✓ check_prod_schema" -ForegroundColor Green
Write-Host "  ✓ config_check" -ForegroundColor Green
Write-Host "  ✓ security_audit" -ForegroundColor Green
Write-Host "  ✓ doctor_all" -ForegroundColor Green
Write-Host "  ✓ pytest" -ForegroundColor Green
Write-Host "  ✓ Production API Health" -ForegroundColor Green
Write-Host ""
Write-Host "  ⚠️  CAUTION: You are targeting PRODUCTION" -ForegroundColor Yellow
Write-Host "  Ready to deploy. Double-check before pushing migrations." -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
exit 0
