param()

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

function Invoke-PythonStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$CaptureOutput
    )

    Write-Host "$Label..." -ForegroundColor Cyan
    $result = & $python @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Host "[FAIL] $Label" -ForegroundColor Red
        if ($result) {
            $result | ForEach-Object { Write-Host "  $_" }
        }
        exit $exitCode
    }

    if ($CaptureOutput) {
        return ,$result
    }

    Write-Host "[OK] $Label" -ForegroundColor Green
    return @()
}

Push-Location -Path $root
try {
    Invoke-PythonStep -Label 'db_check' -Arguments @('-m', 'tools.db_check', '--env', 'prod') | Out-Null
    Invoke-PythonStep -Label 'doctor (prod)' -Arguments @('-m', 'tools.doctor', '--env', 'prod') | Out-Null

    $insertOutput = Invoke-PythonStep -Label 'demo insert case' -Arguments @('-m', 'tools.demo_insert_case', '--env', 'prod') -CaptureOutput
    $insertText = ($insertOutput | Where-Object { $_ -ne $null }) -join [Environment]::NewLine
    try {
        $insertJson = $insertText | ConvertFrom-Json
    }
    catch {
        Write-Host "[FAIL] Could not parse demo insert output as JSON" -ForegroundColor Red
        if ($insertText) {
            Write-Host "  $insertText"
        }
        exit 1
    }

    Write-Host (
        "[OK] Inserted demo case {0} with id {1}" -f $insertJson.case_number, $insertJson.case_id
    ) -ForegroundColor Green
}
finally {
    Pop-Location
}

Write-Host "[OK] demo_smoke_prod completed." -ForegroundColor Green
exit 0
