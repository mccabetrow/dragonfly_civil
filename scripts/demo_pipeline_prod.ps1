param(
    [string]$CaseNumber = 'DEMO-0001'
)

$ErrorActionPreference = 'Stop'

try {
    . (Join-Path -Path $PSScriptRoot -ChildPath 'load_env.ps1')
}
catch {
    Write-Host "[FAIL] Environment load failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$env:SUPABASE_MODE = 'prod'

$prodMap = @{
    'SUPABASE_URL_PROD' = 'SUPABASE_URL'
    'SUPABASE_SERVICE_ROLE_KEY_PROD' = 'SUPABASE_SERVICE_ROLE_KEY'
    'SUPABASE_ANON_KEY_PROD' = 'SUPABASE_ANON_KEY'
    'SUPABASE_DB_URL_PROD' = 'SUPABASE_DB_URL'
    'SUPABASE_DB_PASSWORD_PROD' = 'SUPABASE_DB_PASSWORD'
    'SUPABASE_PROJECT_REF_PROD' = 'SUPABASE_PROJECT_REF'
}

foreach ($sourceName in $prodMap.Keys) {
    if (Test-Path -LiteralPath "Env:$sourceName") {
        $targetName = $prodMap[$sourceName]
        $value = (Get-Item "Env:$sourceName").Value
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            Set-Item -Path "Env:$targetName" -Value $value
        }
    }
}

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path -Path $root -ChildPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}

Write-Host "Running demo pipeline for case $CaseNumber..." -ForegroundColor Cyan

Push-Location -Path $root
try {
    $result = & $python -m tools.demo_pipeline --env prod --case-number $CaseNumber
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Host "[FAIL] demo pipeline" -ForegroundColor Red
        if ($result) {
            $result | ForEach-Object { Write-Host "  $_" }
        }
        exit $exitCode
    }

    if ($result) {
        $result | ForEach-Object { Write-Host $_ }
    }
}
finally {
    Pop-Location
}

Write-Host "[OK] demo pipeline prod completed." -ForegroundColor Green
exit 0
