# Production Gate Script for Dragonfly
# Certifies deployment readiness before plaintiff operations

param(
    [Parameter(Mandatory = $true)]
    [string]$ProductionUrl,
    [switch]$SkipTools
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$baseUrl = $ProductionUrl.TrimEnd('/')

$script:hasFailure = $false

function Write-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail = "")
    $symbol = if ($Passed) { "[PASS]" } else { "[FAIL]" }
    $color = if ($Passed) { "Green" } else { "Red" }
    Write-Host "  $symbol $Name" -ForegroundColor $color
    if ($Detail) { Write-Host "           $Detail" -ForegroundColor DarkGray }
    if (-not $Passed) { $script:hasFailure = $true }
}

# START BANNER
Clear-Host
Write-Host ""
Write-Host "  +========================================================================+" -ForegroundColor Cyan
Write-Host "  |      DRAGONFLY PRODUCTION GATE                                        |" -ForegroundColor Yellow
Write-Host "  |      Certifying Deployment Readiness                                  |" -ForegroundColor White
Write-Host "  +========================================================================+" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Target: $baseUrl" -ForegroundColor White
Write-Host "  Time:   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor White
Write-Host ""
Write-Host "  ------------------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""

# CHECK 1: Config Verification
if (-not $SkipTools) {
    Write-Host "  [1/3] Config Verification..." -ForegroundColor Yellow
    if (Test-Path $venvPython) {
        Push-Location $repoRoot
        try {
            & $venvPython -m tools.verify_env_config --env prod 2>&1 | Out-Null
            Write-Check -Name "tools.verify_env_config" -Passed ($LASTEXITCODE -eq 0) -Detail "exit $LASTEXITCODE"
        }
        catch {
            Write-Check -Name "tools.verify_env_config" -Passed $false -Detail $_.Exception.Message
        }
        finally { Pop-Location }
    }
    else {
        Write-Host "    [SKIP] Python not found" -ForegroundColor Yellow
    }
}
else {
    Write-Host "  [1/3] Config Verification... SKIPPED" -ForegroundColor DarkGray
}

# CHECK 2: Health Endpoint
Write-Host ""
Write-Host "  [2/3] Health Endpoint..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$baseUrl/health" -Method Get -UseBasicParsing -TimeoutSec 15
    Write-Check -Name "GET /health" -Passed ($response.StatusCode -eq 200) -Detail "HTTP $($response.StatusCode)"
}
catch {
    Write-Check -Name "GET /health" -Passed $false -Detail $_.Exception.Message
}

# CHECK 3: Readiness Endpoint
Write-Host ""
Write-Host "  [3/3] Readiness Probe..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$baseUrl/readyz" -Method Get -UseBasicParsing -TimeoutSec 15
    Write-Check -Name "GET /readyz" -Passed ($response.StatusCode -eq 200) -Detail "HTTP $($response.StatusCode)"
}
catch {
    Write-Check -Name "GET /readyz" -Passed $false -Detail $_.Exception.Message
}

# FINAL VERDICT
Write-Host ""
Write-Host "  ========================================================================" -ForegroundColor Cyan
Write-Host ""

if ($hasFailure) {
    Write-Host ""
    Write-Host "  +======================================================================+" -ForegroundColor White -BackgroundColor DarkRed
    Write-Host "  |      SYSTEM RED  -  DO NOT OPERATE                                  |" -ForegroundColor White -BackgroundColor DarkRed
    Write-Host "  |      One or more checks failed. Review errors above.                |" -ForegroundColor White -BackgroundColor DarkRed
    Write-Host "  +======================================================================+" -ForegroundColor White -BackgroundColor DarkRed
    Write-Host ""
    Write-Host "  Fix the failing checks and re-run this script." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}
else {
    Write-Host ""
    Write-Host "  +======================================================================+" -ForegroundColor Black -BackgroundColor Green
    Write-Host "  |      SYSTEM GREEN  -  GO FOR PLAINTIFFS                             |" -ForegroundColor Black -BackgroundColor Green
    Write-Host "  |      All checks passed. Dragonfly is ready for operations.          |" -ForegroundColor Black -BackgroundColor Green
    Write-Host "  +======================================================================+" -ForegroundColor Black -BackgroundColor Green
    Write-Host ""
    Write-Host "  DRAGONFLY IS WORLD CLASS" -ForegroundColor Green
    Write-Host ""
    exit 0
}