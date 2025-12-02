[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

<#
.SYNOPSIS
    Safely promotes the current dev state to prod after all preflight checks pass.
.DESCRIPTION
    Runs the required dev checks (db push, pytest, schema consistency, doctor_all),
    then applies the same migrations + health checks in prod (db push, doctor_all,
    smoke_plaintiffs). Stops immediately on any failure.
#>

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
Set-Location $repoRoot

. (Join-Path $scriptRoot 'load_env.ps1') | Out-Null

$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    Write-Host "[FAIL] Python interpreter not found at $pythonExe. Run scripts/bootstrap.ps1 first." -ForegroundColor Red
    exit 1
}

$dbPushScript = Join-Path $scriptRoot 'db_push.ps1'
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
        [Parameter(Mandatory)][scriptblock]$Command
    )

    Write-Host "  -> $Label"
    $global:LASTEXITCODE = 0
    try {
        & $Command
    }
    catch {
        $exitCode = if ($LASTEXITCODE -ne 0) { $LASTEXITCODE } else { 1 }
        Write-Host "[FAIL] $Label" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
        exit $exitCode
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] $Label (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "[OK] $Label" -ForegroundColor Green
}

# Phase 1 – Dev preflight
Write-Host "[PRE] Dev preflight starting..." -ForegroundColor Yellow
$env:SUPABASE_MODE = 'dev'

Invoke-Step "Dev db_push" {
    & $powershellExe -NoProfile -ExecutionPolicy Bypass -File $dbPushScript -SupabaseEnv dev
}

Invoke-Step "Dev pytest" {
    & $pythonExe -m pytest -q
}

Invoke-Step "Dev schema consistency" {
    & $pythonExe -m tools.check_schema_consistency --env dev
}

Invoke-Step "Dev doctor_all" {
    & $pythonExe -m tools.doctor_all --env dev
}

Write-Host "[PRE] Dev preflight complete. Starting prod promotion..." -ForegroundColor Green

# Phase 2 – Prod promotion
Write-Host "[PRE] Promoting to PROD..." -ForegroundColor Yellow
$env:SUPABASE_MODE = 'prod'

Invoke-Step "Prod db_push" {
    & $powershellExe -NoProfile -ExecutionPolicy Bypass -File $dbPushScript -SupabaseEnv prod
}

Invoke-Step "Prod doctor_all" {
    & $pythonExe -m tools.doctor_all --env prod
}

Invoke-Step "Prod smoke_plaintiffs" {
    & $pythonExe -m tools.smoke_plaintiffs --env prod
}

Write-Host "[SUCCESS] Dev and prod are green. Promotion complete." -ForegroundColor Green
