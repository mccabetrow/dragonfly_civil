<#
.SYNOPSIS
    Simplicity Ingestion Verification - Dec 29th Drill
.DESCRIPTION
    Uploads a CSV file to the Production Intake endpoint and verifies processing:
    1. POST /api/v1/intake/upload - Upload CSV file
    2. Poll /api/v1/intake/batch/{id} - Wait for completion
    3. Verify final status is "completed" or "verified"
.PARAMETER CsvPath
    Path to the CSV file to upload. Required.
.PARAMETER ProdApiKey
    The Dragonfly API key for authenticated endpoints.
    Defaults to $env:PROD_API_KEY or the hardcoded fallback.
.PARAMETER Source
    Source identifier for the upload. Defaults to "simplicity".
.PARAMETER TimeoutSeconds
    Maximum time to wait for batch completion. Defaults to 300 (5 minutes).
.PARAMETER PollIntervalSeconds
    Interval between status polls. Defaults to 5.
.EXAMPLE
    .\scripts\verify_simplicity.ps1 -CsvPath "data\simplicity_sample.csv"
.EXAMPLE
    .\scripts\verify_simplicity.ps1 -CsvPath "data\test.csv" -Source "jbi" -TimeoutSeconds 600
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$CsvPath,

    [string]$ProdApiKey = $env:PROD_API_KEY,

    [string]$Source = "simplicity",

    [int]$TimeoutSeconds = 300,

    [int]$PollIntervalSeconds = 5
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

# ─────────────────────────────────────────────────────────────────────────────
# Validate Input
# ─────────────────────────────────────────────────────────────────────────────
if (-not (Test-Path $CsvPath)) {
    Write-Host "[FAIL] CSV file not found: $CsvPath" -ForegroundColor Red
    exit 1
}

$csvFile = Get-Item $CsvPath
Write-Host ""
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host "  SIMPLICITY INGESTION VERIFICATION" -ForegroundColor White
Write-Host "  Dec 29th Drill - Push-Button Demo" -ForegroundColor DarkGray
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  File:     $($csvFile.Name)" -ForegroundColor White
Write-Host "  Size:     $([math]::Round($csvFile.Length / 1KB, 2)) KB" -ForegroundColor White
Write-Host "  Source:   $Source" -ForegroundColor White
Write-Host "  Timeout:  $TimeoutSeconds seconds" -ForegroundColor White
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Upload CSV File
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ">>> Step 1: Upload CSV to Intake" -ForegroundColor Cyan
Write-Host "    Endpoint: POST /api/v1/intake/upload" -ForegroundColor DarkGray

try {
    $uploadUrl = "$PROD_API_BASE/api/v1/intake/upload?source=$Source"
    
    # Build multipart form data
    $boundary = [System.Guid]::NewGuid().ToString()
    $LF = "`r`n"
    
    $fileBytes = [System.IO.File]::ReadAllBytes($csvFile.FullName)
    $fileEnc = [System.Text.Encoding]::GetEncoding('ISO-8859-1').GetString($fileBytes)
    
    $bodyLines = @(
        "--$boundary",
        "Content-Disposition: form-data; name=`"file`"; filename=`"$($csvFile.Name)`"",
        "Content-Type: text/csv",
        "",
        $fileEnc,
        "--$boundary--"
    )
    $body = $bodyLines -join $LF

    $headers = @{
        'x-dragonfly-api-key' = $ProdApiKey
        'Content-Type'        = "multipart/form-data; boundary=$boundary"
    }

    $response = Invoke-WebRequest -Uri $uploadUrl -Method POST -Headers $headers -Body $body -TimeoutSec 60 -UseBasicParsing
    $uploadResult = $response.Content | ConvertFrom-Json

    if ($response.StatusCode -eq 200 -or $response.StatusCode -eq 201) {
        $batchId = $uploadResult.batch_id
        Write-Host "    [PASS] Upload successful" -ForegroundColor Green
        Write-Host "    Batch ID: $batchId" -ForegroundColor DarkGray
        Write-Host "    Status:   $($uploadResult.status)" -ForegroundColor DarkGray
    }
    else {
        Write-Host "    [FAIL] Upload failed with HTTP $($response.StatusCode)" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "    [FAIL] Upload error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Poll for Batch Completion
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host ">>> Step 2: Polling for Batch Completion" -ForegroundColor Cyan
Write-Host "    Batch ID: $batchId" -ForegroundColor DarkGray
Write-Host "    Polling every $PollIntervalSeconds seconds (timeout: $TimeoutSeconds s)" -ForegroundColor DarkGray
Write-Host ""

$statusUrl = "$PROD_API_BASE/api/v1/intake/batch/$batchId"
$startTime = Get-Date
$finalStatus = $null
$attempts = 0

$terminalStatuses = @('completed', 'verified', 'failed', 'error')

while ($true) {
    $elapsed = ((Get-Date) - $startTime).TotalSeconds
    $attempts++

    if ($elapsed -gt $TimeoutSeconds) {
        Write-Host ""
        Write-Host "[FAIL] Timeout after $TimeoutSeconds seconds" -ForegroundColor Red
        exit 1
    }

    try {
        $pollHeaders = @{ 'x-dragonfly-api-key' = $ProdApiKey }
        $pollResponse = Invoke-WebRequest -Uri $statusUrl -Method GET -Headers $pollHeaders -TimeoutSec 30 -UseBasicParsing
        $batchStatus = $pollResponse.Content | ConvertFrom-Json

        $currentStatus = $batchStatus.status
        $processed = if ($batchStatus.valid_rows) { $batchStatus.valid_rows } else { 0 }
        $errors = if ($batchStatus.error_rows) { $batchStatus.error_rows } else { 0 }
        $total = if ($batchStatus.total_rows) { $batchStatus.total_rows } else { 0 }

        Write-Host "    [$([math]::Round($elapsed))s] Status: $currentStatus | Processed: $processed/$total | Errors: $errors" -ForegroundColor DarkGray

        if ($terminalStatuses -contains $currentStatus.ToLower()) {
            $finalStatus = $currentStatus
            break
        }
    }
    catch {
        Write-Host "    [$([math]::Round($elapsed))s] Poll error: $($_.Exception.Message)" -ForegroundColor Yellow
    }

    Start-Sleep -Seconds $PollIntervalSeconds
}

# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Verify Final Status
# ─────────────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host ">>> Step 3: Verification Result" -ForegroundColor Cyan

$successStatuses = @('completed', 'verified')

if ($successStatuses -contains $finalStatus.ToLower()) {
    Write-Host ""
    Write-Host "===============================================================================" -ForegroundColor Green
    Write-Host "  [OK] Simplicity Ingestion Verified" -ForegroundColor Green
    Write-Host "===============================================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Batch ID:     $batchId" -ForegroundColor White
    Write-Host "  Final Status: $finalStatus" -ForegroundColor White
    Write-Host "  Total Rows:   $total" -ForegroundColor White
    Write-Host "  Valid Rows:   $processed" -ForegroundColor White
    Write-Host "  Error Rows:   $errors" -ForegroundColor White
    Write-Host "  Duration:     $([math]::Round($elapsed)) seconds" -ForegroundColor White
    Write-Host ""
    exit 0
}
else {
    Write-Host ""
    Write-Host "===============================================================================" -ForegroundColor Red
    Write-Host "  [X] Simplicity Ingestion Failed" -ForegroundColor Red
    Write-Host "===============================================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Batch ID:     $batchId" -ForegroundColor White
    Write-Host "  Final Status: $finalStatus" -ForegroundColor Red
    Write-Host "  Total Rows:   $total" -ForegroundColor White
    Write-Host "  Valid Rows:   $processed" -ForegroundColor White
    Write-Host "  Error Rows:   $errors" -ForegroundColor Red
    Write-Host ""
    exit 1
}
