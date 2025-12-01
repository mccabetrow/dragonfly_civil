<#$
.SYNOPSIS
Run all core Dragonfly Civil health checks, stopping on the first failure.
.DESCRIPTION
Loads environment variables, runs database checks, diagnostics, tests, and the dashboard build so "make check-all" has a Windows-friendly equivalent.
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check_all.ps1
#>

param()

$ErrorActionPreference = 'Stop'

. "$PSScriptRoot/load_env.ps1"

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}

function Invoke-Step {
    param(
        [Parameter(Mandatory)]
        [string]$Label,
        [Parameter(Mandatory)]
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
    Invoke-Step "Database check" { & $python '-m' 'tools.db_check' }
    Invoke-Step "Doctor diagnostics" { & $python '-m' 'tools.doctor' }
    Invoke-Step "Pytest suite" { & $python '-m' 'pytest' '-q' }
    Invoke-Step "Dashboard build" {
        Push-Location (Join-Path $root 'dragonfly-dashboard')
        try {
            npm run build
        }
        finally {
            Pop-Location
        }
    }
}
finally {
    Pop-Location
}

# Optional: run pre-commit to catch formatting issues before committing.
# pre-commit run --all-files

Write-Host "All checks completed successfully." -ForegroundColor Green
exit 0
