<#
.SYNOPSIS
    Dragonfly Deployment Verification Script
    Validates API and Worker deployment against expected commit SHA.

.DESCRIPTION
    This script performs two gate checks:
    1. API Gate: Polls the version endpoint until it returns the expected commit SHA
    2. Worker Gate: Checks worker heartbeats in the database for matching version

.PARAMETER ApiBaseUrl
    The base URL of the deployed API (e.g., https://dragonflycivil-production.up.railway.app)

.PARAMETER CommitSha
    The expected Git commit SHA (short or full) that should be deployed

.PARAMETER DbConnectionString
    Optional database connection string. Falls back to SUPABASE_DB_URL env var.

.PARAMETER TimeoutSeconds
    Maximum time to wait for each gate (default: 60)

.EXAMPLE
    .\verify_deployment.ps1 -ApiBaseUrl "https://api.example.com" -CommitSha "abc1234"

.EXAMPLE
    .\verify_deployment.ps1 -ApiBaseUrl $env:API_URL -CommitSha $env:GITHUB_SHA -TimeoutSeconds 120
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ApiBaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$CommitSha,

    [Parameter(Mandatory = $false)]
    [string]$DbConnectionString,

    [Parameter(Mandatory = $false)]
    [int]$TimeoutSeconds = 60,

    [Parameter(Mandatory = $false)]
    [switch]$CheckApiOnly,

    [Parameter(Mandatory = $false)]
    [switch]$CheckWorkerOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# =============================================================================
# Helper Functions
# =============================================================================

function Write-Pass {
    param([string]$Message)
    Write-Host "PASS: " -ForegroundColor Green -NoNewline
    Write-Host $Message
}

function Write-Fail {
    param([string]$Message)
    Write-Host "FAIL: " -ForegroundColor Red -NoNewline
    Write-Host $Message
}

function Write-Info {
    param([string]$Message)
    Write-Host "INFO: " -ForegroundColor Cyan -NoNewline
    Write-Host $Message
}

function Write-Warn {
    param([string]$Message)
    Write-Host "WARN: " -ForegroundColor Yellow -NoNewline
    Write-Host $Message
}

function Write-Header {
    param([string]$Message)
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor DarkGray
    Write-Host $Message -ForegroundColor White
    Write-Host ("=" * 60) -ForegroundColor DarkGray
}

# =============================================================================
# Gate 1: API Version Verification
# =============================================================================

function Test-ApiGate {
    param(
        [string]$BaseUrl,
        [string]$ExpectedSha,
        [int]$Timeout
    )

    Write-Header "GATE 1: API Version Verification"
    Write-Info "Endpoint: $BaseUrl/api/v1/version"
    Write-Info "Expected SHA: $ExpectedSha"
    Write-Info "Timeout: ${Timeout}s"
    Write-Host ""

    $versionUrl = "$BaseUrl/api/v1/version"
    $startTime = Get-Date
    $pollInterval = 5
    $attempt = 0

    while ($true) {
        $attempt++
        $elapsed = [math]::Round(((Get-Date) - $startTime).TotalSeconds, 0)

        if ($elapsed -ge $Timeout) {
            Write-Fail "API gate timed out after ${Timeout}s"
            return $false
        }

        Write-Host "  Attempt $attempt (${elapsed}s elapsed)... " -NoNewline

        try {
            $response = Invoke-RestMethod -Uri $versionUrl -Method Get -TimeoutSec 10 -ErrorAction Stop
            
            # Extract version/commit from response
            $apiVersion = $null
            if ($response.commit) {
                $apiVersion = $response.commit
            } elseif ($response.version) {
                $apiVersion = $response.version
            } elseif ($response.git_sha) {
                $apiVersion = $response.git_sha
            } elseif ($response.sha) {
                $apiVersion = $response.sha
            }

            if (-not $apiVersion) {
                Write-Host "No version in response" -ForegroundColor Yellow
                Start-Sleep -Seconds $pollInterval
                continue
            }

            # Normalize SHAs for comparison (first 7 chars)
            $shaLen = [Math]::Min(7, $ExpectedSha.Length)
            $normalizedExpected = $ExpectedSha.Substring(0, $shaLen).ToLower()
            $actualLen = [Math]::Min(7, $apiVersion.Length)
            $normalizedActual = $apiVersion.Substring(0, $actualLen).ToLower()

            if ($normalizedActual -eq $normalizedExpected) {
                Write-Host "MATCH!" -ForegroundColor Green
                Write-Host ""
                Write-Pass "API is running expected version: $apiVersion"
                return $true
            } else {
                Write-Host "Version mismatch (got: $apiVersion)" -ForegroundColor Yellow
            }

        } catch {
            $errResponse = $_.Exception.Response
            if ($errResponse -and $errResponse.StatusCode) {
                Write-Host "HTTP $($errResponse.StatusCode.value__)" -ForegroundColor Yellow
            } else {
                Write-Host "Connection failed" -ForegroundColor Yellow
            }
        }

        Start-Sleep -Seconds $pollInterval
    }
}

# =============================================================================
# Gate 2: Worker Heartbeat Verification
# =============================================================================

function Test-WorkerGate {
    param(
        [string]$ConnectionString,
        [string]$ExpectedSha,
        [int]$Timeout
    )

    Write-Header "GATE 2: Worker Heartbeat Verification"
    Write-Info "Expected SHA: $ExpectedSha"
    Write-Info "Timeout: ${Timeout}s"
    Write-Host ""

    if (-not $ConnectionString) {
        Write-Warn "No connection string provided, checking env vars..."
        $ConnectionString = $env:SUPABASE_DB_URL
        if (-not $ConnectionString) {
            $ConnectionString = $env:DATABASE_URL
        }
    }

    if (-not $ConnectionString) {
        Write-Fail "No database connection string available"
        Write-Info "Set -DbConnectionString or SUPABASE_DB_URL environment variable"
        return $false
    }

    # Mask the connection string for logging
    $maskedCs = $ConnectionString -replace ':[^@]+@', ':****@'
    Write-Info "Database: $maskedCs"
    Write-Host ""

    $startTime = Get-Date
    $pollInterval = 5
    $attempt = 0

    # Normalize expected SHA
    $shaLen = [Math]::Min(7, $ExpectedSha.Length)
    $normalizedExpected = $ExpectedSha.Substring(0, $shaLen).ToLower()

    # Find Python executable
    $pythonExe = Join-Path $PSScriptRoot ".." ".venv" "Scripts" "python.exe"
    if (-not (Test-Path $pythonExe)) {
        $pythonExe = "python"
    }

    while ($true) {
        $attempt++
        $elapsed = [math]::Round(((Get-Date) - $startTime).TotalSeconds, 0)

        if ($elapsed -ge $Timeout) {
            Write-Fail "Worker gate timed out after ${Timeout}s"
            return $false
        }

        Write-Host "  Attempt $attempt (${elapsed}s elapsed)... " -NoNewline

        try {
            # Use the check_worker_heartbeat.py helper
            $helperScript = Join-Path $PSScriptRoot "check_worker_heartbeat.py"
            
            if (-not (Test-Path $helperScript)) {
                Write-Host "Missing helper script" -ForegroundColor Red
                Write-Fail "check_worker_heartbeat.py not found"
                return $false
            }

            $output = & $pythonExe $helperScript $ConnectionString $normalizedExpected 2>&1
            $result = $output | ConvertFrom-Json

            if ($result.error) {
                Write-Host "DB Error" -ForegroundColor Yellow
                Start-Sleep -Seconds $pollInterval
                continue
            }

            $totalRecent = $result.total_recent
            $matching = $result.matching_count

            if ($matching -gt 0) {
                Write-Host "FOUND $matching matching worker(s)!" -ForegroundColor Green
                Write-Host ""
                Write-Pass "Worker(s) running expected version:"
                foreach ($w in $result.matching) {
                    $age = [math]::Round($w.age_seconds, 1)
                    Write-Host "         - $($w.type)/$($w.id) (age: ${age}s)" -ForegroundColor Green
                }
                return $true
            } else {
                Write-Host "No match ($totalRecent recent workers)" -ForegroundColor Yellow
                if ($result.workers.Count -gt 0) {
                    foreach ($w in $result.workers) {
                        Write-Info "  Found: $($w.type) version=$($w.version)"
                    }
                }
            }

        } catch {
            Write-Host "Error: $_" -ForegroundColor Yellow
        }

        Start-Sleep -Seconds $pollInterval
    }
}

# =============================================================================
# Main Execution
# =============================================================================

Write-Host ""
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host "     DRAGONFLY DEPLOYMENT VERIFICATION                     " -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Info "API Base URL: $ApiBaseUrl"
Write-Info "Expected Commit: $CommitSha"
Write-Info "Timeout per gate: ${TimeoutSeconds}s"
if ($CheckApiOnly) { Write-Info "Mode: API Gate Only" }
if ($CheckWorkerOnly) { Write-Info "Mode: Worker Gate Only" }

$overallSuccess = $true
$apiResult = $true
$workerResult = $true

# Gate 1: API (skip if CheckWorkerOnly)
if (-not $CheckWorkerOnly) {
    $apiResult = Test-ApiGate -BaseUrl $ApiBaseUrl -ExpectedSha $CommitSha -Timeout $TimeoutSeconds
    if (-not $apiResult) {
        $overallSuccess = $false
    }
} else {
    Write-Info "Skipping API gate (--CheckWorkerOnly)"
}

# Gate 2: Workers (skip if CheckApiOnly, or if API failed and not CheckWorkerOnly)
if (-not $CheckApiOnly) {
    if ($apiResult -or $CheckWorkerOnly) {
        $workerResult = Test-WorkerGate -ConnectionString $DbConnectionString -ExpectedSha $CommitSha -Timeout $TimeoutSeconds
        if (-not $workerResult) {
            $overallSuccess = $false
        }
    } else {
        Write-Warn "Skipping worker gate (API gate failed)"
        $overallSuccess = $false
    }
} else {
    Write-Info "Skipping Worker gate (--CheckApiOnly)"
}

# Final Summary
Write-Header "DEPLOYMENT VERIFICATION SUMMARY"

if ($overallSuccess) {
    Write-Host ""
    Write-Host "  ==========================================" -ForegroundColor Green
    Write-Host "   ALL GATES PASSED - DEPLOY OK!            " -ForegroundColor Green
    Write-Host "  ==========================================" -ForegroundColor Green
    Write-Host ""
    exit 0
} else {
    Write-Host ""
    Write-Host "  ==========================================" -ForegroundColor Red
    Write-Host "   DEPLOYMENT VERIFICATION FAILED           " -ForegroundColor Red
    Write-Host "  ==========================================" -ForegroundColor Red
    Write-Host ""
    Write-Fail "Review the failures above before proceeding"
    exit 1
}
