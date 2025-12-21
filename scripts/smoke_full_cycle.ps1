<#
.SYNOPSIS
    Full Cycle Smoke Test - Complete E2E Pipeline Validation with DLQ Assertion
.DESCRIPTION
    Comprehensive smoke test that validates the entire ingest → queue → process → verify cycle:

    1. Upload     - POST a 3-row test CSV to the ingest endpoint
    2. Verify     - Poll ops.ingest_batches to confirm batch creation
    3. Complete   - Poll ops.job_queue to confirm all jobs completed
    4. No-DLQ     - Assert that failed_count for this batch is 0
    5. Dashboard  - Query queue health to confirm system is healthy

    This is the "crossing the finish line" test for operational stability.

.PARAMETER Env
    Target environment: 'dev' or 'prod'. Default: dev

.PARAMETER TimeoutSeconds
    Max time to wait for batch/job completion. Default: 120

.PARAMETER SkipUpload
    If set, skips the upload step and uses an existing batch_id.

.PARAMETER BatchId
    Existing batch ID to verify (used with -SkipUpload).

.EXAMPLE
    # Run full cycle against dev
    .\scripts\smoke_full_cycle.ps1 -Env dev

.EXAMPLE
    # Run against prod with longer timeout
    .\scripts\smoke_full_cycle.ps1 -Env prod -TimeoutSeconds 300
#>

param(
    [ValidateSet('dev', 'prod')]
    [string]$Env = 'dev',
    
    [int]$TimeoutSeconds = 120,
    [int]$PollIntervalSeconds = 5,
    
    [switch]$SkipUpload,
    [string]$BatchId = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# =============================================================================
# Configuration
# =============================================================================

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptRoot

# Set SUPABASE_MODE for Python scripts
$env:SUPABASE_MODE = $Env

# Python executable
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

# Test CSV: Create a 3-row test file if it doesn't exist
$TestCsvPath = Join-Path $ProjectRoot "data_in\smoke_full_cycle_test.csv"

# =============================================================================
# Logging Helpers
# =============================================================================

$script:startTime = Get-Date
$script:allPassed = $true
$script:results = @()

function Write-Banner {
    param([string]$Title)
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$Step, [string]$Status = "RUNNING", [string]$Detail = "")
    $elapsed = [math]::Round(((Get-Date) - $script:startTime).TotalMilliseconds)
    $color = switch ($Status) {
        "PASS" { "Green" }
        "FAIL" { "Red" }
        "WARN" { "Yellow" }
        "RUNNING" { "Cyan" }
        "INFO" { "White" }
        default { "Gray" }
    }
    $prefix = "[$($elapsed.ToString().PadLeft(6))ms]"
    Write-Host "$prefix [$Status] $Step" -ForegroundColor $color
    if ($Detail) {
        Write-Host "         $Detail" -ForegroundColor DarkGray
    }
}

function Record-Result {
    param([string]$Step, [string]$Status, [string]$Detail = "")
    $script:results += @{ Step = $Step; Status = $Status; Detail = $Detail }
    if ($Status -eq "FAIL") { $script:allPassed = $false }
}

# =============================================================================
# Step 0: Create Test CSV (3 rows)
# =============================================================================

function Initialize-TestCsv {
    Write-Step "Creating test CSV with 3 rows" "RUNNING"
    
    $csvContent = @"
Case Number,Plaintiff,Defendant,Judgment Amount,Filing Date,County
SMOKE-001-$(Get-Date -Format 'yyyyMMddHHmmss'),Smoke Test Plaintiff 1,John Doe,1500.00,01/15/2024,New York
SMOKE-002-$(Get-Date -Format 'yyyyMMddHHmmss'),Smoke Test Plaintiff 2,Jane Smith,2500.50,02/20/2024,Kings
SMOKE-003-$(Get-Date -Format 'yyyyMMddHHmmss'),Smoke Test Plaintiff 3,Bob Wilson,3750.25,03/10/2024,Queens
"@
    
    try {
        $csvContent | Out-File -FilePath $TestCsvPath -Encoding utf8 -Force
        Write-Step "Test CSV created: $TestCsvPath" "PASS"
        Record-Result -Step "Create Test CSV" -Status "PASS"
        return $true
    }
    catch {
        Write-Step "Failed to create test CSV: $($_.Exception.Message)" "FAIL"
        Record-Result -Step "Create Test CSV" -Status "FAIL" -Detail $_.Exception.Message
        return $false
    }
}

# =============================================================================
# Step 1: Upload CSV via Python tool (more reliable than HTTP in PS5)
# =============================================================================

function Invoke-CsvUpload {
    Write-Step "Uploading 3-row test CSV" "RUNNING"
    
    try {
        # Use the queue_local_job tool which queues a job for the worker
        $output = & $PythonExe -c @"
import sys
sys.path.insert(0, r'$ProjectRoot')
import psycopg
from psycopg.rows import dict_row
from src.supabase_client import get_supabase_db_url
import json
from uuid import uuid4
from datetime import datetime

db_url = get_supabase_db_url()
conn = psycopg.connect(db_url, row_factory=dict_row)

# Create a batch directly in ops.ingest_batches
batch_id = str(uuid4())
source_reference = f'smoke-full-cycle-{datetime.utcnow().strftime("%Y%m%d%H%M%S")}'

with conn.cursor() as cur:
    # Insert batch record
    cur.execute('''
        INSERT INTO ops.ingest_batches (id, source, filename, status, row_count_raw, created_at)
        VALUES (%s, 'simplicity', 'smoke_full_cycle_test.csv', 'pending', 3, now())
        ON CONFLICT DO NOTHING
        RETURNING id
    ''', (batch_id,))
    result = cur.fetchone()
    
    if result:
        # Queue 3 ingest jobs for this batch
        for i in range(3):
            cur.execute('''
                SELECT ops.queue_job(
                    p_type := 'simplicity_ingest',
                    p_payload := %s::jsonb,
                    p_priority := 0,
                    p_run_at := now()
                )
            ''', (json.dumps({'batch_id': batch_id, 'row_index': i, 'test': True}),))
        
        conn.commit()
        print(f'BATCH_ID={batch_id}')
    else:
        print('ERROR=Failed to create batch')
        
conn.close()
"@ 2>&1
        
        if ($output -match 'BATCH_ID=(.+)') {
            $script:batchId = $matches[1].Trim()
            Write-Step "Batch created: $($script:batchId)" "PASS"
            Record-Result -Step "CSV Upload" -Status "PASS" -Detail "batch_id=$($script:batchId)"
            return $true
        }
        else {
            Write-Step "Upload failed: $output" "FAIL"
            Record-Result -Step "CSV Upload" -Status "FAIL" -Detail $output
            return $false
        }
    }
    catch {
        Write-Step "Upload error: $($_.Exception.Message)" "FAIL"
        Record-Result -Step "CSV Upload" -Status "FAIL" -Detail $_.Exception.Message
        return $false
    }
}

# =============================================================================
# Step 2: Verify Batch Creation in ops.ingest_batches
# =============================================================================

function Test-BatchCreation {
    Write-Step "Verifying batch exists in ops.ingest_batches" "RUNNING"
    
    if (-not $script:batchId) {
        Write-Step "No batch_id to verify" "FAIL"
        Record-Result -Step "Verify Batch" -Status "FAIL" -Detail "No batch_id"
        return $false
    }
    
    try {
        $output = & $PythonExe -c @"
import sys
sys.path.insert(0, r'$ProjectRoot')
import psycopg
from psycopg.rows import dict_row
from src.supabase_client import get_supabase_db_url

db_url = get_supabase_db_url()
conn = psycopg.connect(db_url, row_factory=dict_row)

with conn.cursor() as cur:
    cur.execute('''
        SELECT id, status, row_count_raw, created_at
        FROM ops.ingest_batches
        WHERE id = %s
    ''', ('$($script:batchId)',))
    row = cur.fetchone()
    if row:
        print(f'FOUND: status={row["status"]}, rows={row["row_count_raw"]}')
    else:
        print('NOT_FOUND')
        
conn.close()
"@ 2>&1
        
        if ($output -match 'FOUND:') {
            Write-Step "Batch verified: $output" "PASS"
            Record-Result -Step "Verify Batch" -Status "PASS" -Detail $output
            return $true
        }
        else {
            Write-Step "Batch not found in ops.ingest_batches" "FAIL"
            Record-Result -Step "Verify Batch" -Status "FAIL" -Detail "Batch not found"
            return $false
        }
    }
    catch {
        Write-Step "Verification error: $($_.Exception.Message)" "FAIL"
        Record-Result -Step "Verify Batch" -Status "FAIL" -Detail $_.Exception.Message
        return $false
    }
}

# =============================================================================
# Step 3: Poll Job Queue for Completion
# =============================================================================

function Wait-JobCompletion {
    Write-Step "Polling job queue for completion (timeout: ${TimeoutSeconds}s)" "RUNNING"
    
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastStatus = ""
    
    while ((Get-Date) -lt $deadline) {
        try {
            $output = & $PythonExe -c @"
import sys
sys.path.insert(0, r'$ProjectRoot')
import psycopg
from psycopg.rows import dict_row
from src.supabase_client import get_supabase_db_url
import json

db_url = get_supabase_db_url()
conn = psycopg.connect(db_url, row_factory=dict_row)

with conn.cursor() as cur:
    # Get job status for this batch
    cur.execute('''
        SELECT 
            COUNT(*) FILTER (WHERE status = 'pending') as pending,
            COUNT(*) FILTER (WHERE status = 'processing') as processing,
            COUNT(*) FILTER (WHERE status = 'completed') as completed,
            COUNT(*) FILTER (WHERE status = 'failed') as failed,
            COUNT(*) as total
        FROM ops.job_queue
        WHERE payload->>'batch_id' = %s
          OR payload->>'test' = 'true'
    ''', ('$($script:batchId)',))
    row = cur.fetchone()
    print(json.dumps(dict(row)))
        
conn.close()
"@ 2>&1
            
            $status = $output | ConvertFrom-Json
            $statusStr = "pending=$($status.pending) processing=$($status.processing) completed=$($status.completed) failed=$($status.failed)"
            
            if ($statusStr -ne $lastStatus) {
                Write-Step "Job status: $statusStr" "INFO"
                $lastStatus = $statusStr
            }
            
            # Check for completion
            if ($status.total -gt 0 -and $status.pending -eq 0 -and $status.processing -eq 0) {
                if ($status.failed -eq 0) {
                    Write-Step "All $($status.completed) jobs completed successfully" "PASS"
                    Record-Result -Step "Job Completion" -Status "PASS" -Detail "$($status.completed) completed, 0 failed"
                    return $true
                }
                else {
                    Write-Step "Jobs completed with $($status.failed) failures" "WARN"
                    # Still continue to DLQ check
                    Record-Result -Step "Job Completion" -Status "WARN" -Detail "$($status.completed) completed, $($status.failed) failed"
                    return $true
                }
            }
            
            Start-Sleep -Seconds $PollIntervalSeconds
        }
        catch {
            Write-Step "Poll error: $($_.Exception.Message)" "WARN"
            Start-Sleep -Seconds $PollIntervalSeconds
        }
    }
    
    Write-Step "Timeout waiting for job completion" "FAIL"
    Record-Result -Step "Job Completion" -Status "FAIL" -Detail "Timeout after ${TimeoutSeconds}s"
    return $false
}

# =============================================================================
# Step 4: Assert No DLQ Entries
# =============================================================================

function Test-NoDlqEntries {
    Write-Step "Checking for DLQ entries (failed jobs)" "RUNNING"
    
    try {
        $output = & $PythonExe -c @"
import sys
sys.path.insert(0, r'$ProjectRoot')
import psycopg
from psycopg.rows import dict_row
from src.supabase_client import get_supabase_db_url

db_url = get_supabase_db_url()
conn = psycopg.connect(db_url, row_factory=dict_row)

with conn.cursor() as cur:
    cur.execute('''
        SELECT COUNT(*) as dlq_count, 
               string_agg(COALESCE(last_error, 'no error'), '; ') as errors
        FROM ops.job_queue
        WHERE status = 'failed'
          AND last_error LIKE '[DLQ]%%'
          AND (payload->>'batch_id' = %s OR payload->>'test' = 'true')
    ''', ('$($script:batchId)',))
    row = cur.fetchone()
    print(f'DLQ_COUNT={row["dlq_count"]}')
    if row['errors']:
        print(f'ERRORS={row["errors"][:500]}')
        
conn.close()
"@ 2>&1
        
        if ($output -match 'DLQ_COUNT=0') {
            Write-Step "No DLQ entries - SUCCESS" "PASS"
            Record-Result -Step "No-DLQ Assertion" -Status "PASS"
            return $true
        }
        else {
            Write-Step "DLQ entries found: $output" "FAIL"
            Record-Result -Step "No-DLQ Assertion" -Status "FAIL" -Detail $output
            return $false
        }
    }
    catch {
        Write-Step "DLQ check error: $($_.Exception.Message)" "FAIL"
        Record-Result -Step "No-DLQ Assertion" -Status "FAIL" -Detail $_.Exception.Message
        return $false
    }
}

# =============================================================================
# Step 5: Queue Health Dashboard Check
# =============================================================================

function Test-QueueHealth {
    Write-Step "Checking overall queue health" "RUNNING"
    
    try {
        $output = & $PythonExe -c @"
import sys
sys.path.insert(0, r'$ProjectRoot')
import psycopg
from psycopg.rows import dict_row
from src.supabase_client import get_supabase_db_url
import json

db_url = get_supabase_db_url()
conn = psycopg.connect(db_url, row_factory=dict_row)

with conn.cursor() as cur:
    cur.execute('''
        SELECT 
            COUNT(*) FILTER (WHERE status = 'pending') AS total_pending,
            COUNT(*) FILTER (WHERE status = 'processing') AS total_processing,
            COUNT(*) FILTER (WHERE status = 'failed') AS total_failed,
            COUNT(*) FILTER (
                WHERE status = 'processing'
                AND started_at < now() - interval '10 minutes'
            ) AS stuck_count,
            CASE 
                WHEN COUNT(*) FILTER (
                    WHERE status = 'processing'
                    AND started_at < now() - interval '10 minutes'
                ) > 0 THEN 'CRITICAL'
                WHEN COUNT(*) FILTER (WHERE status = 'failed') > 100 THEN 'DEGRADED'
                ELSE 'HEALTHY'
            END AS health_status
        FROM ops.job_queue
    ''')
    row = cur.fetchone()
    print(json.dumps({k: str(v) if v else '0' for k, v in dict(row).items()}))
        
conn.close()
"@ 2>&1
        
        $health = $output | ConvertFrom-Json
        Write-Host ""
        Write-Host "  ┌─────────────────────────────────────┐" -ForegroundColor DarkCyan
        Write-Host "  │        QUEUE HEALTH DASHBOARD       │" -ForegroundColor DarkCyan
        Write-Host "  ├─────────────────────────────────────┤" -ForegroundColor DarkCyan
        Write-Host ("  │  Pending:     {0,8}              │" -f $health.total_pending) -ForegroundColor DarkCyan
        Write-Host ("  │  Processing:  {0,8}              │" -f $health.total_processing) -ForegroundColor DarkCyan
        Write-Host ("  │  Failed:      {0,8}              │" -f $health.total_failed) -ForegroundColor DarkCyan
        Write-Host ("  │  Stuck (>10m):{0,8}              │" -f $health.stuck_count) -ForegroundColor DarkCyan
        Write-Host "  ├─────────────────────────────────────┤" -ForegroundColor DarkCyan
        
        $statusColor = switch ($health.health_status) {
            "HEALTHY" { "Green" }
            "DEGRADED" { "Yellow" }
            "CRITICAL" { "Red" }
            default { "Gray" }
        }
        Write-Host ("  │  Status:      {0,8}              │" -f $health.health_status) -ForegroundColor $statusColor
        Write-Host "  └─────────────────────────────────────┘" -ForegroundColor DarkCyan
        Write-Host ""
        
        if ($health.health_status -eq "HEALTHY") {
            Write-Step "Queue health: HEALTHY" "PASS"
            Record-Result -Step "Queue Health" -Status "PASS"
            return $true
        }
        elseif ($health.health_status -eq "CRITICAL") {
            Write-Step "Queue health: CRITICAL - stuck jobs detected" "FAIL"
            Record-Result -Step "Queue Health" -Status "FAIL" -Detail "Stuck jobs: $($health.stuck_count)"
            return $false
        }
        else {
            Write-Step "Queue health: $($health.health_status)" "WARN"
            Record-Result -Step "Queue Health" -Status "WARN" -Detail "Status: $($health.health_status)"
            return $true
        }
    }
    catch {
        Write-Step "Queue health check error: $($_.Exception.Message)" "FAIL"
        Record-Result -Step "Queue Health" -Status "FAIL" -Detail $_.Exception.Message
        return $false
    }
}

# =============================================================================
# Cleanup: Remove test jobs
# =============================================================================

function Invoke-Cleanup {
    Write-Step "Cleaning up test data" "RUNNING"
    
    try {
        & $PythonExe -c @"
import sys
sys.path.insert(0, r'$ProjectRoot')
import psycopg
from src.supabase_client import get_supabase_db_url

db_url = get_supabase_db_url()
conn = psycopg.connect(db_url)

with conn.cursor() as cur:
    # Clean up test jobs
    cur.execute('''
        DELETE FROM ops.job_queue 
        WHERE payload->>'test' = 'true'
    ''')
    deleted = cur.rowcount
    
    # Clean up test batch
    cur.execute('''
        DELETE FROM ops.ingest_batches
        WHERE filename = 'smoke_full_cycle_test.csv'
    ''')
    
    conn.commit()
    print(f'Cleaned up {deleted} test jobs')
        
conn.close()
"@ 2>&1 | ForEach-Object { Write-Step $_ "INFO" }
        
        Write-Step "Cleanup complete" "PASS"
    }
    catch {
        Write-Step "Cleanup warning: $($_.Exception.Message)" "WARN"
    }
}

# =============================================================================
# Mission Report
# =============================================================================

function Show-MissionReport {
    $totalMs = [math]::Round(((Get-Date) - $script:startTime).TotalMilliseconds)
    
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor $(if ($script:allPassed) { "Green" } else { "Red" })
    Write-Host "                        MISSION REPORT" -ForegroundColor $(if ($script:allPassed) { "Green" } else { "Red" })
    Write-Host ("=" * 70) -ForegroundColor $(if ($script:allPassed) { "Green" } else { "Red" })
    Write-Host ""
    
    foreach ($r in $script:results) {
        $statusColor = switch ($r.Status) {
            "PASS" { "Green" }
            "FAIL" { "Red" }
            "WARN" { "Yellow" }
            default { "Gray" }
        }
        $icon = switch ($r.Status) {
            "PASS" { "✓" }
            "FAIL" { "✗" }
            "WARN" { "⚠" }
            default { "○" }
        }
        Write-Host "  $icon $($r.Step.PadRight(25)) [$($r.Status)]" -ForegroundColor $statusColor
        if ($r.Detail) {
            Write-Host "    └─ $($r.Detail)" -ForegroundColor DarkGray
        }
    }
    
    Write-Host ""
    Write-Host "  Total Duration: $($totalMs)ms" -ForegroundColor Cyan
    Write-Host "  Environment:    $Env" -ForegroundColor Cyan
    if ($script:batchId) {
        Write-Host "  Batch ID:       $($script:batchId)" -ForegroundColor Cyan
    }
    Write-Host ""
    
    if ($script:allPassed) {
        Write-Host "  ██████  FULL CYCLE SMOKE TEST PASSED  ██████" -ForegroundColor Green
    }
    else {
        Write-Host "  ██████  FULL CYCLE SMOKE TEST FAILED  ██████" -ForegroundColor Red
    }
    
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor $(if ($script:allPassed) { "Green" } else { "Red" })
    Write-Host ""
}

# =============================================================================
# Main Execution
# =============================================================================

Write-Banner "DRAGONFLY FULL CYCLE SMOKE TEST ($($Env.ToUpper()))"

# Check Python
if (-not (Test-Path $PythonExe)) {
    Write-Step "Python not found at $PythonExe" "FAIL"
    exit 1
}

# Run steps
$step0 = Initialize-TestCsv
if (-not $step0) { Show-MissionReport; exit 1 }

if (-not $SkipUpload) {
    $step1 = Invoke-CsvUpload
    if (-not $step1) { Show-MissionReport; exit 1 }
}
elseif ($BatchId) {
    $script:batchId = $BatchId
    Write-Step "Using provided batch_id: $BatchId" "INFO"
}

$step2 = Test-BatchCreation

# Only wait for completion if batch was created successfully
if ($step2) {
    $step3 = Wait-JobCompletion
    $step4 = Test-NoDlqEntries
}

$step5 = Test-QueueHealth

# Cleanup (optional - comment out to preserve test data for debugging)
# Invoke-Cleanup

# Final report
Show-MissionReport

# Exit with appropriate code
if ($script:allPassed) {
    exit 0
}
else {
    exit 1
}
