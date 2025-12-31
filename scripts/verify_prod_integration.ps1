<#
.SYNOPSIS
    Verify Dragonfly Production Connectivity and Environment

.DESCRIPTION
    Comprehensive verification of the Vercel (Frontend) to Railway (Backend) integration:
    1. Lint .env.prod for invisible whitespace issues
    2. Verify HTTP connectivity to Railway endpoints
    3. Verify CORS headers accept Vercel origin
    4. Verify authenticated endpoints work

.PARAMETER Env
    Environment to verify: dev or prod (default: prod)

.PARAMETER SkipLint
    Skip the env file linting step

.PARAMETER SkipConnectivity
    Skip the connectivity verification step

.EXAMPLE
    .\scripts\verify_prod_integration.ps1

.EXAMPLE
    .\scripts\verify_prod_integration.ps1 -Env dev

.EXAMPLE
    .\scripts\verify_prod_integration.ps1 -SkipLint
#>

[CmdletBinding()]
param(
    [ValidateSet("dev", "prod")]
    [string]$Env = "prod",

    [switch]$SkipLint,

    [switch]$SkipConnectivity
)

$ErrorActionPreference = 'Stop'

# Navigate to project root
$ProjectRoot = Join-Path $PSScriptRoot '..'
Set-Location -Path $ProjectRoot

# Activate virtual environment
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    & .\.venv\Scripts\Activate.ps1
}
$env:PYTHONPATH = (Get-Location).Path

$PythonExe = ".\.venv\Scripts\python.exe"

# Banner
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  DRAGONFLY PRODUCTION INTEGRATION VERIFICATION                       " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Environment: $Env" -ForegroundColor Yellow
Write-Host "  Project:     $ProjectRoot" -ForegroundColor Gray
Write-Host ""

$allPassed = $true

# =============================================================================
# STEP 1: LOAD ENVIRONMENT
# =============================================================================

Write-Host "----------------------------------------------------------------------" -ForegroundColor Gray
Write-Host "[STEP 1] Loading Environment Variables..." -ForegroundColor White
Write-Host "----------------------------------------------------------------------" -ForegroundColor Gray
Write-Host ""

$loadEnvScript = Join-Path $PSScriptRoot "load_env.ps1"
if (Test-Path $loadEnvScript) {
    & $loadEnvScript -Mode $Env
    Write-Host ""
}
else {
    Write-Host "  [WARN] load_env.ps1 not found, loading manually..." -ForegroundColor Yellow
    
    $envFile = Join-Path $ProjectRoot ".env.$Env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*#') { return }
            if ($_ -match '^\s*$') { return }
            $name, $value = $_ -split ('=', 2)
            $name = $name.Trim()
            $value = $value.Trim()
            if (-not [string]::IsNullOrWhiteSpace($name)) {
                Set-Item -Path "Env:$name" -Value $value
            }
        }
        Write-Host "  [OK] Loaded .env.$Env" -ForegroundColor Green
    }
    else {
        Write-Host "  [FAIL] .env.$Env not found!" -ForegroundColor Red
        exit 1
    }
}

# =============================================================================
# STEP 2: LINT ENV FILE
# =============================================================================

if (-not $SkipLint) {
    Write-Host ""
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Gray
    Write-Host "[STEP 2] Linting Environment File..." -ForegroundColor White
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Gray
    Write-Host ""

    $lintResult = & $PythonExe -m tools.lint_env_vars --file ".env.$Env" 2>&1
    $lintExitCode = $LASTEXITCODE

    # Display output
    $lintResult | ForEach-Object { Write-Host $_ }

    if ($lintExitCode -eq 0) {
        Write-Host ""
        Write-Host "  [OK] Env file lint: PASSED" -ForegroundColor Green
    }
    else {
        Write-Host ""
        Write-Host "  [FAIL] Env file lint: FAILED" -ForegroundColor Red
        Write-Host "     Fix the issues above before deploying!" -ForegroundColor Yellow
        $allPassed = $false
    }
}
else {
    Write-Host ""
    Write-Host "  [SKIP] Skipping env file lint" -ForegroundColor Gray
}

# =============================================================================
# STEP 3: VERIFY CONNECTIVITY
# =============================================================================

if (-not $SkipConnectivity) {
    Write-Host ""
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Gray
    Write-Host "[STEP 3] Verifying Production Connectivity..." -ForegroundColor White
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Gray
    Write-Host ""

    # Set connectivity environment variables
    if ($Env -eq "prod") {
        $env:PROD_API_URL = "https://dragonflycivil-production-d57a.up.railway.app"
        $env:VERCEL_APP_URL = "https://dragonfly-dashboard.vercel.app"
    }
    else {
        # For dev, use local or staging
        if (-not $env:PROD_API_URL) {
            $env:PROD_API_URL = "http://127.0.0.1:8000"
        }
        if (-not $env:VERCEL_APP_URL) {
            $env:VERCEL_APP_URL = "http://localhost:5173"
        }
    }

    $connectResult = & $PythonExe -m tools.verify_prod_connectivity 2>&1
    $connectExitCode = $LASTEXITCODE

    # Display output
    $connectResult | ForEach-Object { Write-Host $_ }

    if ($connectExitCode -eq 0) {
        Write-Host ""
        Write-Host "  [OK] Connectivity verification: PASSED" -ForegroundColor Green
    }
    else {
        Write-Host ""
        Write-Host "  [FAIL] Connectivity verification: FAILED" -ForegroundColor Red
        $allPassed = $false
    }
}
else {
    Write-Host ""
    Write-Host "  [SKIP] Skipping connectivity verification" -ForegroundColor Gray
}

# =============================================================================
# SUMMARY
# =============================================================================

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan

if ($allPassed) {
    Write-Host "  [OK] ALL VERIFICATION CHECKS PASSED                              " -ForegroundColor Green
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Deployment is ready!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Dashboard: https://dragonfly-dashboard.vercel.app" -ForegroundColor Cyan
    Write-Host "  API:       https://dragonflycivil-production-d57a.up.railway.app" -ForegroundColor Cyan
    Write-Host ""
    exit 0
}
else {
    Write-Host "  [FAIL] VERIFICATION FAILED                                       " -ForegroundColor Red
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Fix the issues above before proceeding with deployment" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}
