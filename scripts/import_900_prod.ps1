<#$
.SYNOPSIS
Bulk import the 900-plaintiff intake file into the production Supabase project.
.DESCRIPTION
Loads environment variables, enforces production guards, validates credentials,
and executes scripts/import_cases_from_csv.py with enrichment jobs enabled.
Never run this script without confirming production keys.
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/import_900_prod.ps1
#>

param(
    [string]$Csv = 'intake_900.csv'
)

$ErrorActionPreference = 'Stop'

try {
    . "$PSScriptRoot/load_env.ps1"
}
catch {
    Write-Host "[FAIL] Environment load failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Environment variables loaded" -ForegroundColor Green

$env:SUPABASE_MODE = 'prod'
$demoEnv = $env:DEMO_ENV
$normalizedDemoEnv = if ([string]::IsNullOrEmpty($demoEnv)) { '' } else { $demoEnv.ToLowerInvariant() }
$blockedDemoEnvs = @('local', 'demo')

Write-Host "Environment guard: DEMO_ENV=$demoEnv SUPABASE_MODE=$($env:SUPABASE_MODE)" -ForegroundColor Yellow
if ($blockedDemoEnvs.Contains($normalizedDemoEnv)) {
    Write-Host "[FAIL] DEMO_ENV must not be 'local' or 'demo' when running the production bulk import." -ForegroundColor Red
    exit 1
}
if ([string]::IsNullOrEmpty($demoEnv)) {
    Write-Host "[FAIL] Set DEMO_ENV to your production label (e.g. 'prod') before running." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Production environment guard satisfied" -ForegroundColor Green

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}

$csvPath = Join-Path $root $Csv
if (-not (Test-Path -LiteralPath $csvPath)) {
    Write-Host "[FAIL] CSV file not found: $csvPath" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] CSV located at $csvPath" -ForegroundColor Green

if ([string]::IsNullOrWhiteSpace($env:SUPABASE_URL_PROD) -or [string]::IsNullOrWhiteSpace($env:SUPABASE_SERVICE_ROLE_KEY_PROD)) {
    Write-Host "[FAIL] SUPABASE_URL_PROD and SUPABASE_SERVICE_ROLE_KEY_PROD must be configured before running." -ForegroundColor Red
    exit 1
}

$importScript = Join-Path $root 'scripts\import_cases_from_csv.py'

$credentialProbe = @'
from src.supabase_client import get_supabase_credentials, get_supabase_db_url
get_supabase_credentials("prod")
get_supabase_db_url("prod")
'@

Write-Host "Validating production Supabase credentials..." -ForegroundColor Cyan
& $python '-c' $credentialProbe
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Production Supabase credentials are missing or invalid." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "[OK] Production Supabase credentials detected." -ForegroundColor Green

function Invoke-Step {
    param(
        [string]$Label,
        [scriptblock]$Command
    )

    Write-Host "$Label..." -ForegroundColor Cyan
    try {
        & $Command
    }
    catch {
        Write-Host "[FAIL] $Label crashed: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }

    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Host "[FAIL] $Label exited with code $exitCode" -ForegroundColor Red
        exit $exitCode
    }

    Write-Host "[OK] $Label" -ForegroundColor Green
}

Push-Location $root
try {
    Invoke-Step "Running production bulk intake" {
        & $python $importScript '--csv' $csvPath '--enqueue-enrich'
    }
}
finally {
    Pop-Location
}

Write-Host "Production bulk intake completed successfully." -ForegroundColor Green
exit 0
