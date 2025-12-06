<#
.SYNOPSIS
Runs the dev health preflight (db push checks, config, security, doctor, pytest).

.DESCRIPTION
Loads .env, scopes Supabase to dev, runs the read-only branch of db_push (checks
mode), and then executes the same checklist ops uses before any meaningful change.
Each step prints a green OK on success and the script exits non-zero at the first
failure. Pass -PytestArgs to narrow the pytest suite when you only need the fast
checks.
#>

[CmdletBinding()]
param(
    [ValidateSet('dev')]
    [string]$SupabaseEnv = 'dev',
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
# PASS/FAIL Summary
# ─────────────────────────────────────────────────────────────────────────────
$stepCount = 6
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
Write-Host "  ✓ config_check" -ForegroundColor Green
Write-Host "  ✓ security_audit" -ForegroundColor Green
Write-Host "  ✓ doctor_all" -ForegroundColor Green
Write-Host "  ✓ pytest" -ForegroundColor Green
Write-Host ""
Write-Host "  Ready for development. All systems operational." -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
exit 0
