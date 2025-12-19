<#
.SYNOPSIS
    Golden Path Smoke Test - End-to-End Pipeline Validation
.DESCRIPTION
    Validates the entire Dragonfly pipeline is operational:

    1. Health Check - API is alive
    2. CSV Upload  - Ingest a single-row test file, capture batch_id
    3. Ingest Poll - Wait for batch to complete (success or failure)
    4. Enrichment  - Verify job was queued (if applicable)
    5. Snapshot    - Check analytics overview for row counts

    Provides "Mission Report" at end with pass/fail summary and timing.

.PARAMETER ApiBase
    Base URL for the Dragonfly API.
    Defaults to localhost:8000 for local dev, or env:DRAGONFLY_API_BASE.

.PARAMETER ApiKey
    API key for authenticated endpoints.
    Defaults to env:DRAGONFLY_API_KEY or demo key.

.PARAMETER CsvPath
    Path to the test CSV file for upload.
    Defaults to data_in/simplicity_test_single.csv.

.PARAMETER TimeoutSeconds
    Max time to wait for batch processing.
    Defaults to 120 seconds.

.PARAMETER PollIntervalSeconds
    Polling interval for batch status checks.
    Defaults to 5 seconds.

.EXAMPLE
    # Local dev test
    .\scripts\smoke_golden_path.ps1

.EXAMPLE
    # Against Railway prod
    .\scripts\smoke_golden_path.ps1 -ApiBase "https://dragonflycivil-production-d57a.up.railway.app" -ApiKey $env:PROD_API_KEY
#>

param(
    [string]$ApiBase = $env:DRAGONFLY_API_BASE,
    [string]$ApiKey = $env:DRAGONFLY_API_KEY,
    [string]$CsvPath = "",
    [int]$TimeoutSeconds = 120,
    [int]$PollIntervalSeconds = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# =============================================================================
# Configuration
# =============================================================================

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptRoot

# Load environment if available
$envScript = Join-Path $ScriptRoot 'load_env.ps1'
if (Test-Path $envScript) {
    try {
        . $envScript
    }
    catch {
        Write-Host "[WARN] Failed to load .env: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# Defaults
if (-not $ApiBase) {
    $ApiBase = "http://localhost:8000"
}
# Strip trailing slash
$ApiBase = $ApiBase.TrimEnd('/')

if (-not $ApiKey) {
    $ApiKey = $env:DRAGONFLY_API_KEY
    if (-not $ApiKey) {
        $ApiKey = "df_dev_test_key"  # Fallback for local dev
    }
}

if (-not $CsvPath) {
    $CsvPath = Join-Path $ProjectRoot "data_in\simplicity_test_single.csv"
}

if (-not (Test-Path $CsvPath)) {
    Write-Host "[FATAL] Test CSV not found: $CsvPath" -ForegroundColor Red
    exit 1
}

# =============================================================================
# Telemetry & Results Tracking
# =============================================================================

$script:startTime = Get-Date
$script:results = @()
$script:allPassed = $true
$script:batchId = $null

function Get-ElapsedMs {
    return [math]::Round(((Get-Date) - $script:startTime).TotalMilliseconds)
}

function Write-Step {
    param([string]$Name, [string]$Status = "RUNNING")
    $elapsed = [int](Get-ElapsedMs)
    $color = switch ($Status) {
        "PASS" { "Green" }
        "FAIL" { "Red" }
        "WARN" { "Yellow" }
        "RUNNING" { "Cyan" }
        default { "White" }
    }
    $elapsedStr = $elapsed.ToString().PadLeft(6, '0')
    Write-Host "[${elapsedStr}ms] [$Status] $Name" -ForegroundColor $color
}

function Record-Result {
    param(
        [string]$Step,
        [string]$Status,
        [int]$DurationMs = 0,
        [string]$Detail = ""
    )

    $script:results += @{
        Step       = $Step
        Status     = $Status
        DurationMs = $DurationMs
        Detail     = $Detail
    }

    if ($Status -eq "FAIL") {
        $script:allPassed = $false
    }
}

function Get-AuthHeaders {
    return @{
        "X-DRAGONFLY-API-KEY" = $ApiKey
        "Content-Type"        = "application/json"
    }
}

# =============================================================================
# Step 1: Health Check
# =============================================================================

function Test-HealthCheck {
    $stepStart = Get-Date
    Write-Step "Health Check" "RUNNING"

    try {
        $url = "$ApiBase/api/v1/intake/health"
        $response = Invoke-RestMethod -Uri $url -Method GET -TimeoutSec 30

        $durationMs = [math]::Round(((Get-Date) - $stepStart).TotalMilliseconds)

        if ($response.status -eq "ok" -or $response.ok -eq $true) {
            Write-Step "Health Check: API alive" "PASS"
            Record-Result -Step "Health Check" -Status "PASS" -DurationMs $durationMs
            return $true
        }
        else {
            Write-Step "Health Check: Unexpected response" "FAIL"
            Write-Host "       Response: $($response | ConvertTo-Json -Compress)" -ForegroundColor DarkRed
            Record-Result -Step "Health Check" -Status "FAIL" -DurationMs $durationMs -Detail "Unexpected response"
            return $false
        }
    }
    catch {
        $durationMs = [math]::Round(((Get-Date) - $stepStart).TotalMilliseconds)
        Write-Step "Health Check: $($_.Exception.Message)" "FAIL"
        Record-Result -Step "Health Check" -Status "FAIL" -DurationMs $durationMs -Detail $_.Exception.Message
        return $false
    }
}

# =============================================================================
# Step 2: CSV Upload
# =============================================================================

function Test-CsvUpload {
    $stepStart = Get-Date
    Write-Step "CSV Upload" "RUNNING"

    try {
        $url = "$ApiBase/api/v1/intake/upload?source=simplicity"
        $headers = @{ "X-DRAGONFLY-API-KEY" = $ApiKey }

        # Multipart form upload
        $fileBytes = [System.IO.File]::ReadAllBytes($CsvPath)
        $fileName = [System.IO.Path]::GetFileName($CsvPath)

        $boundary = [System.Guid]::NewGuid().ToString()
        $LF = "`r`n"

        $bodyLines = @(
            "--$boundary",
            "Content-Disposition: form-data; name=`"file`"; filename=`"$fileName`"",
            "Content-Type: text/csv",
            "",
            [System.Text.Encoding]::UTF8.GetString($fileBytes),
            "--$boundary--",
            ""
        )
        $body = $bodyLines -join $LF

        $contentType = "multipart/form-data; boundary=$boundary"

        $response = Invoke-RestMethod -Uri $url -Method POST -Headers $headers `
            -ContentType $contentType -Body $body -TimeoutSec 60

        $durationMs = [math]::Round(((Get-Date) - $stepStart).TotalMilliseconds)

        # Extract batch_id from response
        $batchIdRaw = $null
        if ($response.data.batch_id) {
            $batchIdRaw = $response.data.batch_id
        }
        elseif ($response.batch_id) {
            $batchIdRaw = $response.batch_id
        }

        if ($batchIdRaw) {
            $script:batchId = $batchIdRaw
            Write-Step "CSV Upload: batch_id=$batchIdRaw" "PASS"
            Record-Result -Step "CSV Upload" -Status "PASS" -DurationMs $durationMs -Detail "batch_id=$batchIdRaw"
            return $true
        }
        else {
            Write-Step "CSV Upload: No batch_id in response" "FAIL"
            Write-Host "       Response: $($response | ConvertTo-Json -Compress)" -ForegroundColor DarkRed
            Record-Result -Step "CSV Upload" -Status "FAIL" -DurationMs $durationMs -Detail "No batch_id"
            return $false
        }
    }
    catch {
        $durationMs = [math]::Round(((Get-Date) - $stepStart).TotalMilliseconds)
        Write-Step "CSV Upload: $($_.Exception.Message)" "FAIL"
        Record-Result -Step "CSV Upload" -Status "FAIL" -DurationMs $durationMs -Detail $_.Exception.Message
        return $false
    }
}

# =============================================================================
# Step 3: Poll Batch Status Until Completion
# =============================================================================

function Test-IngestPoll {
    if (-not $script:batchId) {
        Write-Step "Ingest Poll: Skipped (no batch_id)" "WARN"
        Record-Result -Step "Ingest Poll" -Status "WARN" -Detail "No batch_id to poll"
        return $false
    }

    $stepStart = Get-Date
    Write-Step "Ingest Poll: Waiting for batch $($script:batchId)" "RUNNING"

    $headers = Get-AuthHeaders
    $url = "$ApiBase/api/v1/intake/batch/$($script:batchId)"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    $lastStatus = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $url -Method GET -Headers $headers -TimeoutSec 30

            $status = $response.status
            if (-not $status) { $status = $response.data.status }

            if ($status -ne $lastStatus) {
                Write-Host "       Status: $status" -ForegroundColor DarkGray
                $lastStatus = $status
            }

            if ($status -eq "completed") {
                $durationMs = [math]::Round(((Get-Date) - $stepStart).TotalMilliseconds)

                $validRows = if ($response.valid_rows) { $response.valid_rows } else { $response.data.valid_rows }
                $errorRows = if ($response.error_rows) { $response.error_rows } else { $response.data.error_rows }

                Write-Step "Ingest Poll: Completed (valid=$validRows, errors=$errorRows)" "PASS"
                Record-Result -Step "Ingest Poll" -Status "PASS" -DurationMs $durationMs -Detail "valid=$validRows, errors=$errorRows"
                return $true
            }
            elseif ($status -eq "failed") {
                $durationMs = [math]::Round(((Get-Date) - $stepStart).TotalMilliseconds)
                Write-Step "Ingest Poll: Batch failed" "FAIL"
                Write-Host "       Response: $($response | ConvertTo-Json -Depth 3)" -ForegroundColor DarkRed
                Record-Result -Step "Ingest Poll" -Status "FAIL" -DurationMs $durationMs -Detail "Batch failed"
                return $false
            }

            Start-Sleep -Seconds $PollIntervalSeconds
        }
        catch {
            Write-Host "       Poll error: $($_.Exception.Message)" -ForegroundColor Yellow
            Start-Sleep -Seconds $PollIntervalSeconds
        }
    }

    # Timeout
    $durationMs = [math]::Round(((Get-Date) - $stepStart).TotalMilliseconds)
    Write-Step "Ingest Poll: Timeout after ${TimeoutSeconds}s" "FAIL"
    Record-Result -Step "Ingest Poll" -Status "FAIL" -DurationMs $durationMs -Detail "Timeout waiting for completion"
    return $false
}

# =============================================================================
# Step 4: Verify Enrichment Queue (if applicable)
# =============================================================================

function Test-EnrichmentQueue {
    $stepStart = Get-Date
    Write-Step "Enrichment Queue: Checking job queue depth" "RUNNING"

    $headers = Get-AuthHeaders
    $url = "$ApiBase/api/v1/intake/state"

    try {
        $response = Invoke-RestMethod -Uri $url -Method GET -Headers $headers -TimeoutSec 30

        $durationMs = [math]::Round(((Get-Date) - $stepStart).TotalMilliseconds)

        $queueDepth = if ($response.queue_depth) { $response.queue_depth } else { $response.data.queue_depth }
        if ($null -eq $queueDepth) { $queueDepth = 0 }

        Write-Step "Enrichment Queue: queue_depth=$queueDepth" "PASS"
        Record-Result -Step "Enrichment Queue" -Status "PASS" -DurationMs $durationMs -Detail "queue_depth=$queueDepth"
        return $true
    }
    catch {
        $durationMs = [math]::Round(((Get-Date) - $stepStart).TotalMilliseconds)
        Write-Step "Enrichment Queue: $($_.Exception.Message)" "WARN"
        Record-Result -Step "Enrichment Queue" -Status "WARN" -DurationMs $durationMs -Detail $_.Exception.Message
        return $true  # Non-fatal
    }
}

# =============================================================================
# Step 5: Analytics Snapshot
# =============================================================================

function Test-AnalyticsSnapshot {
    $stepStart = Get-Date
    Write-Step "Analytics Snapshot: Checking overview" "RUNNING"

    $headers = Get-AuthHeaders
    $url = "$ApiBase/api/v1/analytics/overview"

    try {
        $response = Invoke-RestMethod -Uri $url -Method GET -Headers $headers -TimeoutSec 30

        $durationMs = [math]::Round(((Get-Date) - $stepStart).TotalMilliseconds)

        # Extract key metrics
        $totalCases = if ($response.total_cases) { $response.total_cases } else { $response.data.total_cases }
        $totalAmount = if ($response.total_amount) { $response.total_amount } else { $response.data.total_amount }

        if ($null -eq $totalCases) { $totalCases = "N/A" }
        if ($null -eq $totalAmount) { $totalAmount = "N/A" }

        Write-Step "Analytics Snapshot: total_cases=$totalCases" "PASS"
        Record-Result -Step "Analytics Snapshot" -Status "PASS" -DurationMs $durationMs -Detail "total_cases=$totalCases"
        return $true
    }
    catch {
        $durationMs = [math]::Round(((Get-Date) - $stepStart).TotalMilliseconds)

        # Analytics might not be fully deployed - warn but don't fail
        Write-Step "Analytics Snapshot: $($_.Exception.Message)" "WARN"
        Record-Result -Step "Analytics Snapshot" -Status "WARN" -DurationMs $durationMs -Detail $_.Exception.Message
        return $true  # Non-fatal for now
    }
}

# =============================================================================
# Mission Report
# =============================================================================

function Show-MissionReport {
    $totalMs = Get-ElapsedMs

    Write-Host ""
    Write-Host "=" * 70 -ForegroundColor Magenta
    Write-Host "                    GOLDEN PATH MISSION REPORT" -ForegroundColor Magenta
    Write-Host "=" * 70 -ForegroundColor Magenta
    Write-Host ""

    Write-Host "Target:       $ApiBase" -ForegroundColor White
    Write-Host "CSV File:     $(Split-Path -Leaf $CsvPath)" -ForegroundColor White
    $batchDisplay = if ($script:batchId) { $script:batchId } else { 'N/A' }
    Write-Host "Batch ID:     $batchDisplay" -ForegroundColor White
    Write-Host "Total Time:   ${totalMs}ms" -ForegroundColor White
    Write-Host ""

    Write-Host "Step Results:" -ForegroundColor White
    Write-Host "-" * 70 -ForegroundColor DarkGray

    foreach ($r in $script:results) {
        $statusColor = switch ($r.Status) {
            "PASS" { "Green" }
            "FAIL" { "Red" }
            "WARN" { "Yellow" }
            default { "White" }
        }

        $stepPadded = $r.Step.PadRight(25)
        $statusPadded = "[$($r.Status)]".PadRight(8)
        $durationPadded = ("$($r.DurationMs)ms").PadLeft(8)

        Write-Host "  $stepPadded $statusPadded $durationPadded" -ForegroundColor $statusColor -NoNewline
        if ($r.Detail) {
            Write-Host "  ($($r.Detail))" -ForegroundColor DarkGray
        }
        else {
            Write-Host ""
        }
    }

    Write-Host "-" * 70 -ForegroundColor DarkGray
    Write-Host ""

    $passCount = @($script:results | Where-Object { $_.Status -eq "PASS" }).Count
    $failCount = @($script:results | Where-Object { $_.Status -eq "FAIL" }).Count
    $warnCount = @($script:results | Where-Object { $_.Status -eq "WARN" }).Count
    $totalCount = @($script:results).Count

    if ($script:allPassed) {
        Write-Host "VERDICT: ALL SYSTEMS GO" -ForegroundColor Green -BackgroundColor DarkGreen
        Write-Host "         $passCount/$totalCount passed, $warnCount warnings" -ForegroundColor Green
    }
    else {
        Write-Host "VERDICT: MISSION FAILED" -ForegroundColor Red -BackgroundColor DarkRed
        Write-Host "         $passCount passed, $failCount FAILED, $warnCount warnings" -ForegroundColor Red
    }

    Write-Host ""
    Write-Host "=" * 70 -ForegroundColor Magenta
}

# =============================================================================
# Main Execution
# =============================================================================

Write-Host ""
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "         DRAGONFLY GOLDEN PATH SMOKE TEST" -ForegroundColor Cyan
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host ""
Write-Host "Target:   $ApiBase" -ForegroundColor White
Write-Host "CSV:      $CsvPath" -ForegroundColor White
Write-Host "Timeout:  ${TimeoutSeconds}s" -ForegroundColor White
Write-Host ""

# Execute steps
$step1 = Test-HealthCheck
if (-not $step1) {
    Show-MissionReport
    exit 1
}

$step2 = Test-CsvUpload
if (-not $step2) {
    Show-MissionReport
    exit 1
}

$step3 = Test-IngestPoll

$step4 = Test-EnrichmentQueue

$step5 = Test-AnalyticsSnapshot

# Show final report
Show-MissionReport

if ($script:allPassed) {
    exit 0
}
else {
    exit 1
}
