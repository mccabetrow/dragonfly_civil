<#$
.SYNOPSIS
Bulk import the 900-plaintiff intake file into the demo Supabase project.
.DESCRIPTION
Loads the standard demo environment, enforces non-production guards, and runs
python -m etl.src.importers.jbi_900 against the canonical run/plaintiffs file,
recording a timestamped batch name so logs stay traceable.
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/import_900_demo.ps1
#>

param(
    [string]$Csv = 'run/plaintiffs_canonical.csv'
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

$env:SUPABASE_MODE = 'demo'
$allowedDemoEnvs = @('local', 'demo')
$demoEnv = $env:DEMO_ENV
$normalizedDemoEnv = if ([string]::IsNullOrEmpty($demoEnv)) { '' } else { $demoEnv.ToLowerInvariant() }

Write-Host "Environment guard: DEMO_ENV=$demoEnv SUPABASE_MODE=$($env:SUPABASE_MODE)" -ForegroundColor Yellow
if (-not $allowedDemoEnvs.Contains($normalizedDemoEnv)) {
    Write-Host "[FAIL] DEMO_ENV must be 'local' or 'demo' for the demo bulk import." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Demo environment guard satisfied" -ForegroundColor Green

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

$batchName = "demo_900_{0}" -f (Get-Date -Format 'yyyyMMddHHmmss')
Write-Host "[INFO] Using batch name $batchName" -ForegroundColor Yellow

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
    Invoke-Step "Running demo bulk intake" {
        & $python '-m' 'etl.src.importers.jbi_900' $csvPath '--batch-name' $batchName '--commit'
    }
}
finally {
    Pop-Location
}

Write-Host "Demo bulk intake completed successfully." -ForegroundColor Green
exit 0
