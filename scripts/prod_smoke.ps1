<#
.SYNOPSIS
    Production E2E Smoke Test - Push-Button Demo
.DESCRIPTION
    Verifies the entire Dragonfly platform is operational:
    1. API Health Check
    2. Intake Batches Endpoint (authenticated)
    3. Cases Pipeline Endpoint (authenticated)
    4. Supabase View Query (v_enforcement_overview)
.PARAMETER ProdApiKey
    The Dragonfly API key for authenticated endpoints.
    Defaults to $env:PROD_API_KEY or the hardcoded fallback.
.EXAMPLE
    .\scripts\prod_smoke.ps1
.EXAMPLE
    .\scripts\prod_smoke.ps1 -ProdApiKey "df_prod_xxxxx"
#>
param(
    [string]$ProdApiKey = $env:PROD_API_KEY
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
$PROD_API_BASE = "https://dragonflycivil-production-d57a.up.railway.app"

# Fallback API key if not provided
if (-not $ProdApiKey) {
    $ProdApiKey = "df_prod_3d50b1f2-9f1a-4d8e-b4ab-7b2e2b4c9b73"
}

# Load environment variables
$envPath = Join-Path (Join-Path $PSScriptRoot '..') '.env'
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
        $name, $value = $_ -split '=', 2
        if ($name -and $value) {
            Set-Item -Path "Env:$($name.Trim())" -Value $value.Trim()
        }
    }
}

$SUPABASE_URL = $env:SUPABASE_URL_PROD
$SUPABASE_KEY = $env:SUPABASE_SERVICE_ROLE_KEY_PROD

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────
$script:allPassed = $true
$script:results = @()

function Write-Pass {
    param([string]$Message)
    Write-Host "[PASS] $Message" -ForegroundColor Green
    $script:results += @{ Status = 'PASS'; Message = $Message }
}

function Write-Fail {
    param([string]$Message, [string]$Detail = '')
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    if ($Detail) {
        Write-Host "       $Detail" -ForegroundColor DarkRed
    }
    $script:allPassed = $false
    $script:results += @{ Status = 'FAIL'; Message = $Message }
}

function Invoke-ApiCheck {
    param(
        [string]$Name,
        [string]$Url,
        [hashtable]$Headers = @{},
        [switch]$ExpectJson
    )

    Write-Host ""
    Write-Host ">>> $Name" -ForegroundColor Cyan
    Write-Host "    URL: $Url" -ForegroundColor DarkGray

    try {
        $response = Invoke-WebRequest -Uri $Url -Method GET -Headers $Headers -TimeoutSec 30 -UseBasicParsing
        $statusCode = $response.StatusCode

        if ($statusCode -eq 200) {
            if ($ExpectJson) {
                $json = $response.Content | ConvertFrom-Json
                Write-Host "    Status: $statusCode OK" -ForegroundColor DarkGreen
                Write-Host "    Response: Valid JSON" -ForegroundColor DarkGreen
                Write-Pass $Name
                return $json
            }
            else {
                Write-Host "    Status: $statusCode OK" -ForegroundColor DarkGreen
                Write-Pass $Name
                return $response.Content
            }
        }
        else {
            Write-Fail $Name "HTTP $statusCode"
            return $null
        }
    }
    catch {
        $errorMsg = $_.Exception.Message
        Write-Fail $Name $errorMsg
        return $null
    }
}

function Invoke-SupabaseQuery {
    param(
        [string]$Name,
        [string]$Table,
        [string]$Select = '*',
        [int]$Limit = 1
    )

    Write-Host ""
    Write-Host ">>> $Name" -ForegroundColor Cyan

    if (-not $SUPABASE_URL -or -not $SUPABASE_KEY) {
        Write-Fail $Name "Missing SUPABASE_URL_PROD or SUPABASE_SERVICE_ROLE_KEY_PROD"
        return $null
    }

    $url = "$SUPABASE_URL/rest/v1/$Table`?select=$Select&limit=$Limit"
    Write-Host "    URL: $url" -ForegroundColor DarkGray

    $headers = @{
        'apikey'        = $SUPABASE_KEY
        'Authorization' = "Bearer $SUPABASE_KEY"
        'Content-Type'  = 'application/json'
    }

    try {
        $response = Invoke-WebRequest -Uri $url -Method GET -Headers $headers -TimeoutSec 30 -UseBasicParsing
        $statusCode = $response.StatusCode

        if ($statusCode -eq 200) {
            $json = $response.Content | ConvertFrom-Json
            $rowCount = if ($json -is [array]) { $json.Count } else { 1 }
            Write-Host "    Status: $statusCode OK" -ForegroundColor DarkGreen
            Write-Host "    Rows: $rowCount" -ForegroundColor DarkGreen
            Write-Pass $Name
            return $json
        }
        else {
            Write-Fail $Name "HTTP $statusCode"
            return $null
        }
    }
    catch {
        $errorMsg = $_.Exception.Message
        Write-Fail $Name $errorMsg
        return $null
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host "  DRAGONFLY PRODUCTION SMOKE TEST" -ForegroundColor White
Write-Host "  Push-Button E2E Verification" -ForegroundColor DarkGray
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Target API:  $PROD_API_BASE" -ForegroundColor White
Write-Host "  Supabase:    $SUPABASE_URL" -ForegroundColor White
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: API Health Check
# ─────────────────────────────────────────────────────────────────────────────
$health = Invoke-ApiCheck -Name "API Health (/health)" -Url "$PROD_API_BASE/health" -ExpectJson
if ($health) {
    Write-Host "    Service: $($health.service)" -ForegroundColor DarkGray
    Write-Host "    Status:  $($health.status)" -ForegroundColor DarkGray
}

# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Intake Batches Endpoint (Authenticated)
# ─────────────────────────────────────────────────────────────────────────────
$authHeaders = @{ 'x-dragonfly-api-key' = $ProdApiKey }
$batches = Invoke-ApiCheck -Name "Intake Batches (/api/v1/intake/batches)" -Url "$PROD_API_BASE/api/v1/intake/batches?page=1&page_size=5" -Headers $authHeaders -ExpectJson
if ($batches) {
    $batchCount = if ($batches.batches) { $batches.batches.Count } else { 0 }
    Write-Host "    Total Batches: $($batches.total)" -ForegroundColor DarkGray
    Write-Host "    Returned: $batchCount" -ForegroundColor DarkGray
}

# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Cases Pipeline Endpoint (Authenticated)
# ─────────────────────────────────────────────────────────────────────────────
$pipeline = Invoke-ApiCheck -Name "Cases Pipeline (/api/v1/cases/pipeline)" -Url "$PROD_API_BASE/api/v1/cases/pipeline" -Headers $authHeaders -ExpectJson
if ($pipeline) {
    $caseCount = if ($pipeline -is [array]) { $pipeline.Count } else { 1 }
    Write-Host "    Cases: $caseCount" -ForegroundColor DarkGray
}

# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Supabase View Query (public.v_enforcement_overview)
# ─────────────────────────────────────────────────────────────────────────────
$portfolio = Invoke-SupabaseQuery -Name "Database View (v_enforcement_overview)" -Table "v_enforcement_overview" -Limit 5
if ($portfolio) {
    Write-Host "    View is readable and returns data" -ForegroundColor DarkGray
}

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host "  SMOKE TEST SUMMARY" -ForegroundColor White
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host ""

$passCount = ($script:results | Where-Object { $_.Status -eq 'PASS' }).Count
$failCount = ($script:results | Where-Object { $_.Status -eq 'FAIL' }).Count

foreach ($r in $script:results) {
    if ($r.Status -eq 'PASS') {
        Write-Host "  [PASS] $($r.Message)" -ForegroundColor Green
    }
    else {
        Write-Host "  [FAIL] $($r.Message)" -ForegroundColor Red
    }
}

Write-Host ""

if ($script:allPassed) {
    Write-Host "===============================================================================" -ForegroundColor Green
    Write-Host "  RESULT: ALL CHECKS PASSED ($passCount/$passCount)" -ForegroundColor Green
    Write-Host "===============================================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  [OK] API: Online" -ForegroundColor Green
    Write-Host "  [OK] Database: Connected" -ForegroundColor Green
    Write-Host "  [OK] Ingest Pipeline: Ready" -ForegroundColor Green
    Write-Host ""
    exit 0
}
else {
    Write-Host "===============================================================================" -ForegroundColor Red
    Write-Host "  RESULT: FAILURE ($failCount check(s) failed)" -ForegroundColor Red
    Write-Host "===============================================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "  [X] FAILURE - Production is NOT fully operational" -ForegroundColor Red
    Write-Host ""
    exit 1
}
