<#$
.SYNOPSIS
Reset the demo dataset, smoke check the dashboard views, and run a demo pipeline case.
.DESCRIPTION
Seeds the deterministic plaintiffs via tools.seed_demo_plaintiffs, verifies the
plaintiff + enforcement dashboard views, and runs tools.demo_pipeline so a fresh
case is ready for walkthroughs. Never point this script at prod credentials.
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo_reset_and_smoke.ps1
#>

param()

$ErrorActionPreference = 'Stop'

. "$PSScriptRoot/load_env.ps1"

$allowedDemoEnvs = @('local', 'demo')
$demoEnv = $env:DEMO_ENV
$nodeEnv = $env:NODE_ENV
$supabaseModeRaw = $env:SUPABASE_MODE
$normalizedDemoEnv = if ([string]::IsNullOrEmpty($demoEnv)) { '' } else { $demoEnv.ToLowerInvariant() }
$normalizedNodeEnv = if ([string]::IsNullOrEmpty($nodeEnv)) { '' } else { $nodeEnv.ToLowerInvariant() }
$normalizedSupabaseMode = if ([string]::IsNullOrEmpty($supabaseModeRaw)) { 'demo' } else { $supabaseModeRaw.ToLowerInvariant() }

Write-Host "Environment guard: DEMO_ENV=$demoEnv NODE_ENV=$nodeEnv SUPABASE_MODE=$supabaseModeRaw" -ForegroundColor Yellow
if (-not $allowedDemoEnvs.Contains($normalizedDemoEnv)) {
    Write-Host "[FAIL] DEMO_ENV must be 'local' or 'demo'" -ForegroundColor Red
    exit 1
}
if ($normalizedNodeEnv -eq 'production') {
    Write-Host "[FAIL] NODE_ENV=production is not allowed for demo resets" -ForegroundColor Red
    exit 1
}
if ($normalizedSupabaseMode -eq 'prod' -or $normalizedSupabaseMode -eq 'production') {
    Write-Host "[FAIL] SUPABASE_MODE=$supabaseModeRaw blocks demo resets. Set SUPABASE_MODE=dev before running." -ForegroundColor Red
    exit 1
}

if ($normalizedSupabaseMode -ne 'dev') {
    Write-Host "[WARN] Forcing SUPABASE_MODE=dev so seed + smoke checks hit the demo dataset" -ForegroundColor Yellow
    $env:SUPABASE_MODE = 'dev'
    $normalizedSupabaseMode = 'dev'
}

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}

function Invoke-PythonModule {
    param(
        [string]$Module,
        [string[]]$Arguments = @()
    )

    & $python '-m' $Module @Arguments
}

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
    Invoke-Step "Seeding deterministic demo plaintiffs" {
        Invoke-PythonModule -Module 'tools.seed_demo_plaintiffs' -Arguments @('--reset')
    }
    Invoke-Step "Running plaintiff smoke checks" {
        Invoke-PythonModule -Module 'tools.smoke_plaintiffs'
    }
    Invoke-Step "Running enforcement smoke checks" {
        Invoke-PythonModule -Module 'tools.smoke_enforcement'
    }
    Invoke-Step "Running demo pipeline case" {
        Invoke-PythonModule -Module 'tools.demo_pipeline' -Arguments @('--timeout', '180')
    }
}
finally {
    Pop-Location
}

Write-Host "Demo reset + smoke checks completed successfully." -ForegroundColor Green
exit 0
