<#
.SYNOPSIS
    Dragonfly Production Smoke Test
    Exercises the full ingest loop: Upload CSV -> Process -> Validate

.DESCRIPTION
    This script performs an end-to-end smoke test:
    1. Uploads a small smoke test CSV to the ingest API
    2. Polls the batch status until completion
    3. Validates the job count matches the CSV row count
    4. Optionally cleans up or logs batch ID for manual cleanup

.PARAMETER ApiBaseUrl
    The base URL of the deployed API (e.g., https://dragonflycivil-production.up.railway.app)

.PARAMETER ApiKey
    The API key for authentication. Falls back to DRAGONFLY_API_KEY env var.

.PARAMETER TimeoutSeconds
    Maximum time to wait for batch completion (default: 120)

.PARAMETER SkipCleanup
    If set, skips the cleanup step and just logs the batch ID

.EXAMPLE
    .\smoke_production.ps1 -ApiBaseUrl "https://api.example.com"

.EXAMPLE
    .\smoke_production.ps1 -ApiBaseUrl $env:API_URL -ApiKey $env:API_KEY -TimeoutSeconds 180
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ApiBaseUrl,

    [Parameter(Mandatory = $false)]
    [string]$ApiKey,

    [Parameter(Mandatory = $false)]
    [int]$TimeoutSeconds = 120,

    [Parameter(Mandatory = $false)]
    [switch]$SkipCleanup
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
# Smoke Test CSV Generator
# =============================================================================

function New-SmokeTestCsv {
    $timestamp = Get-Date -Format "yyyyMMddHHmmss"
    $smokeId = "SMOKE-$timestamp"
    
    # Create a minimal valid CSV with 3 test rows
    $lines = @(
        "case_number,debtor_name,judgment_amount,judgment_date,court_name,plaintiff_name"
        "$smokeId-001,Smoke Test Debtor One,1000.00,2024-01-15,Test County Court,Smoke Test Plaintiff"
        "$smokeId-002,Smoke Test Debtor Two,2500.50,2024-02-20,Test County Court,Smoke Test Plaintiff"
        "$smokeId-003,Smoke Test Debtor Three,500.25,2024-03-10,Test County Court,Smoke Test Plaintiff"
    )
    $csvContent = $lines -join "`n"

    $tempFile = [System.IO.Path]::GetTempFileName() -replace '\.tmp$', '.csv'
    Set-Content -Path $tempFile -Value $csvContent -Encoding UTF8
    
    return @{
        Path = $tempFile
        RowCount = 3
        SmokeId = $smokeId
    }
}

# =============================================================================
# Step 1: Upload CSV
# =============================================================================

function Invoke-CsvUpload {
    param(
        [string]$BaseUrl,
        [string]$CsvPath,
        [string]$Key,
        [string]$SmokeId
    )

    Write-Header "STEP 1: Upload Smoke Test CSV"
    Write-Info "File: $CsvPath"
    Write-Info "Smoke ID: $SmokeId"
    Write-Host ""

    $uploadUrl = "$BaseUrl/api/v1/ingest/upload"
    
    # Build headers
    $headers = @{
        "Accept" = "application/json"
    }
    if ($Key) {
        $headers["X-API-Key"] = $Key
    }

    try {
        # Create multipart form data
        $form = @{
            file = Get-Item -Path $CsvPath
            batch_name = "smoke-test-$SmokeId"
            source = "smoke_test"
        }

        Write-Host "  Uploading... " -NoNewline

        $response = Invoke-RestMethod -Uri $uploadUrl -Method Post -Headers $headers -Form $form -TimeoutSec 30

        if ($response.batch_id) {
            Write-Host "SUCCESS!" -ForegroundColor Green
            Write-Pass "Batch created: $($response.batch_id)"
            return @{
                Success = $true
                BatchId = $response.batch_id
                Response = $response
            }
        } elseif ($response.id) {
            Write-Host "SUCCESS!" -ForegroundColor Green
            Write-Pass "Batch created: $($response.id)"
            return @{
                Success = $true
                BatchId = $response.id
                Response = $response
            }
        } else {
            Write-Host "Unexpected response" -ForegroundColor Yellow
            Write-Info "Response: $($response | ConvertTo-Json -Compress)"
            return @{ Success = $false }
        }

    } catch {
        Write-Host "FAILED" -ForegroundColor Red
        Write-Fail "Upload failed: $_"
        
        $errResponse = $_.Exception.Response
        if ($errResponse -and $errResponse.StatusCode) {
            Write-Info "HTTP Status: $($errResponse.StatusCode.value__)"
        }
        
        return @{ Success = $false }
    }
}

# =============================================================================
# Step 2: Poll Batch Status
# =============================================================================

function Wait-BatchCompletion {
    param(
        [string]$BaseUrl,
        [string]$BatchId,
        [string]$Key,
        [int]$Timeout
    )

    Write-Header "STEP 2: Wait for Batch Completion"
    Write-Info "Batch ID: $BatchId"
    Write-Info "Timeout: ${Timeout}s"
    Write-Host ""

    $statusUrl = "$BaseUrl/api/v1/ingest/batches/$BatchId"
    
    $headers = @{
        "Accept" = "application/json"
    }
    if ($Key) {
        $headers["X-API-Key"] = $Key
    }

    $startTime = Get-Date
    $pollInterval = 3
    $attempt = 0

    while ($true) {
        $attempt++
        $elapsed = [math]::Round(((Get-Date) - $startTime).TotalSeconds, 0)

        if ($elapsed -ge $Timeout) {
            Write-Fail "Batch processing timed out after ${Timeout}s"
            return @{ Success = $false; Status = "timeout" }
        }

        Write-Host "  Poll $attempt (${elapsed}s)... " -NoNewline

        try {
            $response = Invoke-RestMethod -Uri $statusUrl -Method Get -Headers $headers -TimeoutSec 10

            $status = $response.status
            $jobsTotal = $response.jobs_total
            $jobsCompleted = $response.jobs_completed
            $jobsFailed = $response.jobs_failed

            $statusColor = switch ($status) {
                "completed" { "Green" }
                "failed" { "Red" }
                "processing" { "Yellow" }
                default { "Gray" }
            }

            Write-Host "$status " -NoNewline -ForegroundColor $statusColor
            Write-Host "($jobsCompleted/$jobsTotal done, $jobsFailed failed)" -ForegroundColor Gray

            if ($status -eq "completed") {
                Write-Host ""
                Write-Pass "Batch completed successfully"
                return @{
                    Success = $true
                    Status = $status
                    Response = $response
                    JobsTotal = $jobsTotal
                    JobsCompleted = $jobsCompleted
                    JobsFailed = $jobsFailed
                }
            } elseif ($status -eq "failed") {
                Write-Host ""
                Write-Fail "Batch failed"
                return @{
                    Success = $false
                    Status = $status
                    Response = $response
                }
            }

        } catch {
            $errResponse = $_.Exception.Response
            if ($errResponse -and $errResponse.StatusCode) {
                Write-Host "HTTP $($errResponse.StatusCode.value__)" -ForegroundColor Yellow
            } else {
                Write-Host "Error" -ForegroundColor Yellow
            }
        }

        Start-Sleep -Seconds $pollInterval
    }
}

# =============================================================================
# Step 3: Validate Results
# =============================================================================

function Test-BatchResults {
    param(
        [int]$ExpectedRows,
        [object]$BatchResult
    )

    Write-Header "STEP 3: Validate Results"
    Write-Info "Expected rows: $ExpectedRows"
    Write-Host ""

    $success = $true

    # Check job count matches
    if ($BatchResult.JobsTotal -eq $ExpectedRows) {
        Write-Pass "Job count matches CSV row count ($ExpectedRows)"
    } else {
        Write-Fail "Job count mismatch: expected $ExpectedRows, got $($BatchResult.JobsTotal)"
        $success = $false
    }

    # Check all jobs completed (not failed)
    if ($BatchResult.JobsFailed -eq 0) {
        Write-Pass "No failed jobs"
    } else {
        Write-Warn "$($BatchResult.JobsFailed) job(s) failed"
        $success = $false
    }

    # Check completed count
    if ($BatchResult.JobsCompleted -eq $ExpectedRows) {
        Write-Pass "All $($BatchResult.JobsCompleted) jobs completed"
    } else {
        Write-Fail "Not all jobs completed: $($BatchResult.JobsCompleted)/$ExpectedRows"
        $success = $false
    }

    return $success
}

# =============================================================================
# Step 4: Cleanup
# =============================================================================

function Invoke-Cleanup {
    param(
        [string]$BaseUrl,
        [string]$BatchId,
        [string]$Key,
        [switch]$Skip
    )

    Write-Header "STEP 4: Cleanup"

    if ($Skip) {
        Write-Info "Cleanup skipped (--SkipCleanup)"
        Write-Info "Batch ID for manual cleanup: $BatchId"
        return
    }

    # Try to call cleanup endpoint if it exists
    $cleanupUrl = "$BaseUrl/api/v1/ingest/batches/$BatchId/cleanup"
    
    $headers = @{
        "Accept" = "application/json"
    }
    if ($Key) {
        $headers["X-API-Key"] = $Key
    }

    try {
        Write-Host "  Attempting cleanup... " -NoNewline
        $response = Invoke-RestMethod -Uri $cleanupUrl -Method Delete -Headers $headers -TimeoutSec 10
        Write-Host "SUCCESS" -ForegroundColor Green
        Write-Pass "Batch $BatchId cleaned up"
    } catch {
        $errResponse = $_.Exception.Response
        if ($errResponse -and $errResponse.StatusCode -and $errResponse.StatusCode.value__ -eq 404) {
            Write-Host "No cleanup endpoint" -ForegroundColor Yellow
            Write-Info "Batch ID for manual cleanup: $BatchId"
        } else {
            Write-Host "Failed" -ForegroundColor Yellow
            Write-Warn "Could not cleanup batch: $BatchId"
        }
    }
}

# =============================================================================
# Main Execution
# =============================================================================

Write-Host ""
Write-Host "===========================================================" -ForegroundColor Magenta
Write-Host "     DRAGONFLY PRODUCTION SMOKE TEST                       " -ForegroundColor Magenta
Write-Host "===========================================================" -ForegroundColor Magenta
Write-Host ""

# Resolve API key
if (-not $ApiKey) {
    $ApiKey = $env:DRAGONFLY_API_KEY
    if ($ApiKey) {
        Write-Info "Using API key from DRAGONFLY_API_KEY env var"
    } else {
        Write-Warn "No API key provided (may fail if API requires auth)"
    }
}

Write-Info "API Base URL: $ApiBaseUrl"
Write-Info "Timeout: ${TimeoutSeconds}s"

$overallSuccess = $true
$batchId = $null
$csvInfo = $null

try {
    # Generate smoke test CSV
    $csvInfo = New-SmokeTestCsv
    Write-Info "Generated smoke test CSV with $($csvInfo.RowCount) rows"

    # Step 1: Upload
    $uploadResult = Invoke-CsvUpload -BaseUrl $ApiBaseUrl -CsvPath $csvInfo.Path -Key $ApiKey -SmokeId $csvInfo.SmokeId
    if (-not $uploadResult.Success) {
        $overallSuccess = $false
        throw "Upload failed"
    }
    $batchId = $uploadResult.BatchId

    # Step 2: Wait for completion
    $batchResult = Wait-BatchCompletion -BaseUrl $ApiBaseUrl -BatchId $batchId -Key $ApiKey -Timeout $TimeoutSeconds
    if (-not $batchResult.Success) {
        $overallSuccess = $false
        throw "Batch processing failed: $($batchResult.Status)"
    }

    # Step 3: Validate
    $validationResult = Test-BatchResults -ExpectedRows $csvInfo.RowCount -BatchResult $batchResult
    if (-not $validationResult) {
        $overallSuccess = $false
    }

    # Step 4: Cleanup
    Invoke-Cleanup -BaseUrl $ApiBaseUrl -BatchId $batchId -Key $ApiKey -Skip:$SkipCleanup

} catch {
    Write-Fail "Smoke test error: $_"
    $overallSuccess = $false
} finally {
    # Clean up temp CSV
    if ($csvInfo -and (Test-Path $csvInfo.Path)) {
        Remove-Item $csvInfo.Path -Force -ErrorAction SilentlyContinue
    }
}

# Final Summary
Write-Header "SMOKE TEST SUMMARY"

if ($batchId) {
    Write-Info "Batch ID: $batchId"
}

if ($overallSuccess) {
    Write-Host ""
    Write-Host "  ==========================================" -ForegroundColor Green
    Write-Host "   SMOKE TEST PASSED - PRODUCTION IS GO!    " -ForegroundColor Green
    Write-Host "  ==========================================" -ForegroundColor Green
    Write-Host ""
    exit 0
} else {
    Write-Host ""
    Write-Host "  ==========================================" -ForegroundColor Red
    Write-Host "   SMOKE TEST FAILED - INVESTIGATE!         " -ForegroundColor Red
    Write-Host "  ==========================================" -ForegroundColor Red
    Write-Host ""
    if ($batchId) {
        Write-Fail "Check batch $batchId for details"
    }
    exit 1
}
