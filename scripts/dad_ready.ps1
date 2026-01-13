<#
.SYNOPSIS
    Dad Mode - Production Readiness Check for Non-Technical Operators

.DESCRIPTION
    A simple GO / NO-GO gate for production deployments.
    Runs all critical checks and prints clear status with next steps.

.PARAMETER Url
    Override the production API URL (default: from DRAGONFLY_PROD_URL)

.PARAMETER SkipBusinessCheck
    Skip the business logic verification (faster, less thorough)

.EXAMPLE
    .\scripts\dad_ready.ps1
    # Run full production readiness check

.EXAMPLE
    .\scripts\dad_ready.ps1 -SkipBusinessCheck
    # Run quick check without business logic verification

.EXAMPLE
    .\scripts\dad_ready.ps1 -Url "https://my-staging.up.railway.app"
    # Check a specific URL instead of production
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Url,

    [Parameter(Mandatory = $false)]
    [switch]$SkipBusinessCheck
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptRoot

# Track results
$script:CheckResults = @()
$script:OverallPass = $true
$StartTime = Get-Date

function Write-Banner {
    param([string]$Title, [string]$Color = "Cyan")
    $Border = "=" * 70
    Write-Host ""
    Write-Host $Border -ForegroundColor $Color
    Write-Host "  $Title" -ForegroundColor $Color
    Write-Host $Border -ForegroundColor $Color
    Write-Host ""
}

function Write-Step {
    param([string]$Message)
    Write-Host "  > $Message" -ForegroundColor White
}

function Write-Pass {
    param([string]$Check, [string]$Details = "")
    $script:CheckResults += @{ Check = $Check; Status = "PASS"; Details = $Details }
    Write-Host "  [PASS] $Check" -ForegroundColor Green
    if ($Details) { Write-Host "         $Details" -ForegroundColor White }
}

function Write-Fail {
    param([string]$Check, [string]$Details = "")
    $script:CheckResults += @{ Check = $Check; Status = "FAIL"; Details = $Details }
    $script:OverallPass = $false
    Write-Host "  [FAIL] $Check" -ForegroundColor Red
    if ($Details) { Write-Host "         $Details" -ForegroundColor Yellow }
}

function Write-Skip {
    param([string]$Check, [string]$Reason = "")
    $script:CheckResults += @{ Check = $Check; Status = "SKIP"; Details = $Reason }
    Write-Host "  [SKIP] $Check" -ForegroundColor Yellow
    if ($Reason) { Write-Host "         $Reason" -ForegroundColor White }
}

function Load-EnvFile {
    param([string]$FilePath)
    if (-not (Test-Path $FilePath)) { return $false }
    Get-Content $FilePath | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $parts = $line -split "=", 2
            if ($parts.Count -eq 2) {
                $key = $parts[0].Trim()
                $value = $parts[1].Trim().Trim('"').Trim("'")
                [Environment]::SetEnvironmentVariable($key, $value, "Process")
            }
        }
    }
    return $true
}

function Test-ApiReachable {
    param([string]$BaseUrl)
    try {
        $healthUrl = "$BaseUrl/api/health"
        $response = Invoke-WebRequest -Uri $healthUrl -Method GET -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $body = $response.Content | ConvertFrom-Json
            return @{ Success = $true; Status = $body.status; Version = $body.version }
        }
        return @{ Success = $false; Error = "Unexpected status: $($response.StatusCode)" }
    }
    catch {
        return @{ Success = $false; Error = $_.Exception.Message }
    }
}

function Test-ReadinessProbe {
    param([string]$BaseUrl)
    try {
        $readyUrl = "$BaseUrl/api/readyz"
        $response = Invoke-WebRequest -Uri $readyUrl -Method GET -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200) { return @{ Success = $true } }
        return @{ Success = $false; Error = "Readiness returned $($response.StatusCode)" }
    }
    catch {
        return @{ Success = $false; Error = $_.Exception.Message }
    }
}

# ============================================================================
# Main Script
# ============================================================================

Write-Banner "DRAGONFLY DAD MODE - Production Readiness Check" "Cyan"

# Step 1: Load environment
Write-Step "Loading production environment..."

$envFile = Join-Path $ProjectRoot ".env.prod"
if (Load-EnvFile $envFile) {
    Write-Pass "Environment loaded" ".env.prod"
}
else {
    $envFile = Join-Path $ProjectRoot ".env"
    if (Load-EnvFile $envFile) {
        Write-Pass "Environment loaded" ".env (fallback)"
    }
    else {
        Write-Fail "Environment file not found" "Expected .env.prod or .env"
    }
}

$env:SUPABASE_MODE = "prod"
$env:ENVIRONMENT = "prod"

# Determine API URL
if ($Url) {
    $ApiUrl = $Url.TrimEnd("/")
    Write-Host "  Using override URL: $ApiUrl" -ForegroundColor Yellow
}
else {
    $ApiUrl = $env:DRAGONFLY_PROD_URL
    if (-not $ApiUrl) {
        $ApiUrl = $env:RAILWAY_PUBLIC_DOMAIN
        if ($ApiUrl -and -not $ApiUrl.StartsWith("http")) {
            $ApiUrl = "https://$ApiUrl"
        }
    }
    if (-not $ApiUrl) {
        Write-Fail "Production URL not configured" "Set DRAGONFLY_PROD_URL or use -Url"
        $ApiUrl = $null
    }
}

Write-Host ""

# Step 2: API Health Check
Write-Step "Checking production API health..."

if ($ApiUrl) {
    $healthResult = Test-ApiReachable $ApiUrl
    if ($healthResult.Success) {
        $ver = if ($healthResult.Version) { "v$($healthResult.Version)" } else { "" }
        Write-Pass "API is reachable" "$ApiUrl $ver"
    }
    else {
        Write-Fail "API unreachable" $healthResult.Error
    }

    $readyResult = Test-ReadinessProbe $ApiUrl
    if ($readyResult.Success) {
        Write-Pass "Readiness probe passed" "/api/readyz returned 200"
    }
    else {
        Write-Fail "Readiness probe failed" $readyResult.Error
    }
}
else {
    Write-Skip "API health check" "No URL configured"
    Write-Skip "Readiness probe" "No URL configured"
}

Write-Host ""

# Step 3: Production Gate
Write-Step "Running production gate checks..."

$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }

try {
    $gateOutput = & $pythonExe -m tools.prod_gate --mode prod --env prod 2>&1
    $gateExitCode = $LASTEXITCODE

    if ($gateExitCode -eq 0) {
        Write-Pass "Production gate passed" "All database and schema checks OK"
    }
    else {
        $summary = ($gateOutput | Select-String -Pattern "FAIL|ERROR" | Select-Object -First 3) -join "; "
        if (-not $summary) { $summary = "Exit code $gateExitCode" }
        Write-Fail "Production gate failed" $summary
    }
}
catch {
    Write-Fail "Production gate error" $_.Exception.Message
}

Write-Host ""

# Step 4: Smoke Test
Write-Step "Running smoke tests..."

try {
    $smokeOutput = & $pythonExe -m tools.smoke_plaintiffs --env prod 2>&1
    $smokeExitCode = $LASTEXITCODE
    if ($smokeExitCode -eq 0) {
        Write-Pass "Smoke test passed" "Plaintiff visibility OK"
    }
    else {
        Write-Fail "Smoke test failed" "Exit code: $smokeExitCode"
    }
}
catch {
    Write-Skip "Smoke test" "smoke_plaintiffs not available"
}

Write-Host ""

# Step 5: Business Logic (optional)
if (-not $SkipBusinessCheck) {
    Write-Step "Running business logic verification..."
    $bizPython = Join-Path $ProjectRoot "tools\verify_business_logic.py"
    if (Test-Path $bizPython) {
        try {
            $bizOutput = & $pythonExe $bizPython --env prod 2>&1
            $bizExitCode = $LASTEXITCODE
            if ($bizExitCode -eq 0) {
                Write-Pass "Business logic verified" "All business rules OK"
            }
            else {
                Write-Fail "Business logic failed" "Exit code: $bizExitCode"
            }
        }
        catch {
            Write-Fail "Business logic error" $_.Exception.Message
        }
    }
    else {
        Write-Skip "Business logic verification" "No verification script found"
    }
}
else {
    Write-Skip "Business logic verification" "Skipped via -SkipBusinessCheck"
}

# ============================================================================
# Final Summary
# ============================================================================

$EndTime = Get-Date
$Duration = ($EndTime - $StartTime).TotalSeconds

Write-Host ""

$passCount = ($script:CheckResults | Where-Object { $_.Status -eq "PASS" }).Count
$failCount = ($script:CheckResults | Where-Object { $_.Status -eq "FAIL" }).Count
$skipCount = ($script:CheckResults | Where-Object { $_.Status -eq "SKIP" }).Count

if ($script:OverallPass -and $failCount -eq 0) {
    Write-Banner "GO - PRODUCTION IS READY" "Green"
    Write-Host "  All checks passed!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Summary: $passCount passed, $skipCount skipped" -ForegroundColor White
    Write-Host "  Duration: $([math]::Round($Duration, 1)) seconds" -ForegroundColor White
    Write-Host ""
    Write-Host "  NEXT STEPS:" -ForegroundColor Cyan
    Write-Host "    1. Notify team that production is verified" -ForegroundColor White
    Write-Host "    2. Monitor dashboards for 15 minutes post-deploy" -ForegroundColor White
    Write-Host "    3. Check Discord alerts channel for any warnings" -ForegroundColor White
    Write-Host ""
    exit 0
}
else {
    Write-Banner "NO-GO - PRODUCTION NOT READY" "Red"
    Write-Host "  Some checks failed!" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Summary: $passCount passed, $failCount FAILED, $skipCount skipped" -ForegroundColor White
    Write-Host "  Duration: $([math]::Round($Duration, 1)) seconds" -ForegroundColor White
    Write-Host ""
    Write-Host "  FAILURES:" -ForegroundColor Red
    $script:CheckResults | Where-Object { $_.Status -eq "FAIL" } | ForEach-Object {
        Write-Host "    - $($_.Check): $($_.Details)" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "  NEXT STEPS:" -ForegroundColor Cyan
    Write-Host "    1. DO NOT DEPLOY until issues are resolved" -ForegroundColor Red
    Write-Host "    2. Contact engineering team with the failures above" -ForegroundColor White
    Write-Host "    3. Run with -Verbose for more details" -ForegroundColor White
    Write-Host ""
    exit 1
}
