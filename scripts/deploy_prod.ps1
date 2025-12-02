<#
.SYNOPSIS
Runs the full production deployment pipeline.

.DESCRIPTION
Loads environment variables, runs the prod preflight checklist, applies all Supabase
migrations against prod, and builds the dashboard static assets. Use -SkipPreflight if
preflight already ran in the same shell, and -PytestArgs to forward pytest limits to the
preflight stage.
#>

[CmdletBinding()]
param(
    [switch]$SkipPreflight,
    [string[]]$PytestArgs
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'load_env.ps1') | Out-Null
$env:SUPABASE_MODE = 'prod'

function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][scriptblock]$Action
    )

    Write-Host "`n→ $Label" -ForegroundColor Cyan
    try {
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

if (-not $SkipPreflight) {
    $preflightScript = Join-Path $PSScriptRoot 'preflight_prod.ps1'
    if (-not (Test-Path -LiteralPath $preflightScript)) {
        throw "Unable to find preflight_prod.ps1 at $preflightScript"
    }

    Invoke-Step "Preflight (prod)" {
        & $preflightScript -SupabaseEnv 'prod' -PytestArgs $PytestArgs
    }
}
else {
    Write-Host "[INFO] Skipping prod preflight as requested." -ForegroundColor Yellow
}

$dbPushScript = Join-Path $PSScriptRoot 'db_push.ps1'
if (-not (Test-Path -LiteralPath $dbPushScript)) {
    throw "Unable to find db_push.ps1 at $dbPushScript"
}

Invoke-Step "Apply Supabase migrations to prod" {
    & $dbPushScript -SupabaseEnv 'prod' -Mode 'All'
}

$dashboardDir = Join-Path $repoRoot 'dragonfly-dashboard'
if (-not (Test-Path -LiteralPath $dashboardDir)) {
    throw "Unable to find dragonfly-dashboard directory at $dashboardDir"
}

Invoke-Step "Build dashboard static assets" {
    Push-Location $dashboardDir
    try {
        $npm = Get-Command npm -ErrorAction Stop
        & $npm.Source run build
    }
    finally {
        Pop-Location
    }
}

Write-Host "`n[OK] Production deployment finished." -ForegroundColor Green
Write-Host "Steps: preflight → db_push (prod) → dashboard build"
Write-Host "Dashboard bundle: $(Join-Path $dashboardDir 'dist')"
