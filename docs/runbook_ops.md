# Dragonfly Ops Runbook

**Version**: 1.0  
**Last Updated**: 2025-01-04  
**Audience**: Operations Console Operators, On-Call Engineers

---

## Table of Contents

1. [Quick Reference](#quick-reference)
2. [Incident: Batch Stuck in Processing](#incident-batch-stuck-in-processing)
3. [Incident: High Error Rate (>10%)](#incident-high-error-rate-10)
4. [Incident: Dashboard 500 Errors (PGRST002)](#incident-dashboard-500-errors-pgrst002)
5. [Procedure: Force Re-ingest](#procedure-force-re-ingest)
6. [Procedure: Manual Batch Cleanup](#procedure-manual-batch-cleanup)
7. [Alert Routing](#alert-routing)
8. [Emergency Contacts](#emergency-contacts)

---

## Quick Reference

### Health Check Commands

```bash
# Check pipeline health (dev)
SUPABASE_MODE=dev python -m backend.workers.sentinel

# Check pipeline health (prod) - JSON output
SUPABASE_MODE=prod python -m backend.workers.sentinel --json

# Check database connectivity
SUPABASE_MODE=prod python -m tools.doctor --env prod
```

### Common Paths

| Resource           | Dev                                                                        | Prod                                                                        |
| ------------------ | -------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| Backend Logs       | `logs/worker.log`                                                          | `/var/log/dragonfly/worker.log`                                             |
| Sentinel Logs      | Console output                                                             | `/var/log/dragonfly/sentinel.log`                                           |
| Supabase Dashboard | [Dev Project](https://supabase.com/dashboard/project/ejiddanxtqcleyswqvkc) | [Prod Project](https://supabase.com/dashboard/project/iaketsyhmqbwaabgykux) |

---

## Incident: Batch Stuck in Processing

### Symptoms

- Batch shows `status='processing'` or `status='validating'` for > 10 minutes
- Sentinel alert: `"stuck_batches": "3 batches stuck > 10m"`
- Dashboard shows "Processing..." indefinitely

### Detection

```bash
# Run Sentinel to detect stuck batches
SUPABASE_MODE=prod python -m backend.workers.sentinel

# Or query database directly
psql $SUPABASE_DB_URL -c "
SELECT
    id,
    status,
    filename,
    created_at,
    EXTRACT(EPOCH FROM (NOW() - created_at)) / 60 AS age_minutes
FROM intake.simplicity_batches
WHERE status IN ('uploaded', 'staging', 'validating', 'transforming', 'inserting', 'upserting', 'processing')
ORDER BY created_at ASC;
"
```

### Diagnosis

#### Step 1: Check Backend Logs

```bash
# Dev
tail -f logs/worker.log | grep -i error

# Prod
ssh ops@dragonfly-prod
tail -f /var/log/dragonfly/worker.log | grep -i error
```

**Look for**:

- `asyncpg.exceptions.QueryCanceledError` (DB timeout)
- `ConnectionRefusedError` (DB unavailable)
- Python exceptions in validation/transformation logic

#### Step 2: Check Database Connections

```bash
# Query active connections (service role)
psql $SUPABASE_DB_URL -c "
SELECT
    count(*) as active_connections,
    state,
    wait_event_type
FROM pg_stat_activity
WHERE usename = 'dragonfly_app'
GROUP BY state, wait_event_type;
"
```

#### Step 3: Check Batch Details

```bash
# Get batch metadata
SUPABASE_MODE=prod python -c "
from src.supabase_client import create_supabase_client
sb = create_supabase_client()
result = sb.schema('intake').table('simplicity_batches').select('*').eq('id', '<BATCH_ID>').execute()
print(result.data)
"
```

### Resolution

#### Option A: Reset Batch (Recommended)

Reset the batch to `uploaded` state so the worker can retry:

```bash
# Manual reset via SQL
psql $SUPABASE_DB_URL -c "
UPDATE intake.simplicity_batches
SET
    status = 'uploaded',
    updated_at = NOW()
WHERE id = '<BATCH_ID>';
"

# Verify reset
psql $SUPABASE_DB_URL -c "
SELECT id, status, filename, created_at
FROM intake.simplicity_batches
WHERE id = '<BATCH_ID>';
"
```

**Expected Outcome**: Worker picks up batch within 30 seconds and retries processing.

#### Option B: Force Fail Batch

If batch is corrupted or unrecoverable:

```bash
psql $SUPABASE_DB_URL -c "
UPDATE intake.simplicity_batches
SET
    status = 'failed',
    rejection_reason = 'Manually failed: stuck in processing > 30 minutes',
    updated_at = NOW()
WHERE id = '<BATCH_ID>';
"
```

**Expected Outcome**: Batch marked as failed, no further processing attempts.

#### Option C: Restart Worker Process

If multiple batches are stuck (worker process crashed):

```bash
# Systemd (prod)
sudo systemctl restart dragonfly-worker

# Railway (auto-restarts on crash)
# Force restart via Railway dashboard

# Dev (kill and restart manually)
pkill -f "worker.py"
python -m backend.worker &
```

**Expected Outcome**: Worker restarts, picks up pending batches within 1 minute.

### Escalation

If issue persists after resolution attempts:

1. **Check Supabase status**: https://status.supabase.com
2. **Review recent migrations**: Last schema change may have broken worker
3. **Contact Engineering**: Slack #dragonfly-alerts with batch ID and logs

---

## Incident: High Error Rate (>10%)

### Symptoms

- Sentinel alert: `"error_spike": "Error rate 18.5% > 15.0% threshold"`
- Dashboard shows red "🔴 Batch Rejected" status
- Batch has `rejection_reason` populated

### Detection

```bash
# Run Sentinel to detect error spikes
SUPABASE_MODE=prod python -m backend.workers.sentinel --json

# Or query last hour's error rate
psql $SUPABASE_DB_URL -c "
SELECT
    hour_bucket,
    total_batches,
    total_rows,
    error_rows,
    ROUND(100.0 * error_rows / NULLIF(total_rows, 0), 2) AS error_rate_pct
FROM ops.v_batch_performance
WHERE hour_bucket >= NOW() - INTERVAL '1 hour'
ORDER BY hour_bucket DESC;
"
```

### Diagnosis

#### Step 1: Check Error Distribution

```sql
-- Top 10 error codes in last 24 hours
SELECT
    error_code,
    occurrence_count,
    affected_batches,
    sample_message,
    last_seen_at
FROM ops.v_error_distribution
ORDER BY occurrence_count DESC
LIMIT 10;
```

**Common Error Codes**:

- `MISSING_REQUIRED_FIELD` - Source file missing column (e.g., case_number)
- `INVALID_DATE_FORMAT` - Date format mismatch (expected YYYY-MM-DD)
- `DUPLICATE_CASE_NUMBER` - Row violates unique constraint
- `VALIDATION_ERROR` - General validation failure

#### Step 2: Download Error CSV

```bash
# Get batch errors
psql $SUPABASE_DB_URL -c "
COPY (
    SELECT
        batch_id,
        row_index + 1 AS row_number,
        error_code,
        error_message,
        created_at
    FROM intake.row_errors
    WHERE batch_id = '<BATCH_ID>'
    ORDER BY row_index
) TO STDOUT WITH CSV HEADER;
" > /tmp/batch_errors.csv

# Or via API
curl -X GET "https://iaketsyhmqbwaabgykux.supabase.co/rest/v1/row_errors?batch_id=eq.<BATCH_ID>&select=*" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  > /tmp/batch_errors.json
```

#### Step 3: Identify Root Cause

**Systemic Issues** (multiple batches):

- Schema change broke validation (recent migration?)
- New data source with different format
- Upstream vendor changed export format

**One-Off Issues** (single batch):

- Corrupted CSV file
- Manual export with wrong columns
- Incomplete data dump

### Resolution

#### Option A: Fix Source Data and Re-upload

```bash
# 1. Download original file from storage
gsutil cp gs://dragonfly-intake/batches/<BATCH_ID>.csv /tmp/original.csv

# 2. Fix issues in Excel/Python (e.g., add missing columns, fix dates)
# Example: Add missing 'case_number' column
awk -F',' 'NR==1 {print $0",case_number"; next} {print $0",CASE-"NR}' /tmp/original.csv > /tmp/fixed.csv

# 3. Re-upload via IntakeStation (dashboard)
# Or via API:
curl -X POST "https://dragonfly-api.railway.app/api/intake/upload" \
  -H "Authorization: Bearer $DRAGONFLY_API_KEY" \
  -F "file=@/tmp/fixed.csv" \
  -F "source=simplicity"
```

#### Option B: Adjust Error Threshold

If errors are expected (e.g., known bad data from vendor):

```sql
-- Increase threshold for specific batch
UPDATE intake.simplicity_batches
SET error_threshold_percent = 25
WHERE id = '<BATCH_ID>';

-- Reprocess batch (reset to uploaded)
UPDATE intake.simplicity_batches
SET status = 'uploaded', updated_at = NOW()
WHERE id = '<BATCH_ID>';
```

**Expected Outcome**: Batch reprocesses with higher error tolerance, inserts valid rows, skips invalid.

#### Option C: Update Validation Rules

If validation is too strict (engineering task):

```bash
# 1. Identify failing validation in code
grep -r "MISSING_REQUIRED_FIELD" backend/services/

# 2. Update validation logic (requires code change + deployment)
# Example: Make 'defendant_address' optional instead of required

# 3. Deploy updated worker
git commit -am "fix: Make defendant_address optional in Simplicity adapter"
git push origin main
# Railway auto-deploys
```

### Escalation

If error rate remains high after fixes:

1. **Coordinate with Data Team**: Verify vendor export format hasn't changed
2. **Review Validation Rules**: May need to relax constraints for new data source
3. **Contact Engineering**: Slack #dragonfly-alerts with error CSV

---

## Incident: Dashboard 500 Errors (PGRST002)

### Symptoms

- Dashboard shows blank screens or "Failed to fetch" errors
- Browser console: `500 Internal Server Error`
- PostgREST logs: `"code": "PGRST002"`, `"message": "Could not query the database for the schema cache. Retrying."`

### Detection

```bash
# Check PostgREST health via Sentinel
SUPABASE_MODE=prod python -m backend.workers.sentinel

# Or test endpoint directly
curl -I https://iaketsyhmqbwaabgykux.supabase.co/rest/v1/simplicity_batches \
  -H "apikey: $SUPABASE_ANON_KEY"
# Look for: HTTP/2 503 Service Unavailable
```

### Diagnosis

#### Step 1: Check Supabase Dashboard

1. Go to [Supabase Dashboard](https://supabase.com/dashboard/project/iaketsyhmqbwaabgykux)
2. Click **Logs** > **PostgREST Logs**
3. Look for: `PGRST002` or `schema cache` errors

#### Step 2: Check Recent Migrations

```bash
# List recent migrations
ls -lt supabase/migrations/ | head -5

# Check if migration was applied recently
psql $SUPABASE_DB_URL -c "
SELECT version, name, inserted_at
FROM supabase_migrations.schema_migrations
ORDER BY inserted_at DESC
LIMIT 5;
"
```

**PGRST002 often occurs**:

- After schema migration (new tables/views/columns)
- After RLS policy changes
- During high load (connection pool exhaustion)

### Resolution

#### Option A: Auto-Reload via Sentinel (Preferred)

Sentinel automatically sends `NOTIFY pgrst, 'reload'` when it detects PGRST002:

```bash
# Run Sentinel once - it will auto-reload if needed
SUPABASE_MODE=prod python -m backend.workers.sentinel

# Check logs for:
# "[schema_cache] Sent NOTIFY pgrst, 'reload' - schema reloading"
```

**Expected Outcome**: PostgREST reloads schema within 5-10 seconds, dashboard recovers.

#### Option B: Manual Reload via SQL

```bash
# Connect to database and send reload notification
psql $SUPABASE_DB_URL -c "NOTIFY pgrst, 'reload';"

# Wait 10 seconds, then test endpoint
sleep 10
curl -I https://iaketsyhmqbwaabgykux.supabase.co/rest/v1/simplicity_batches \
  -H "apikey: $SUPABASE_ANON_KEY"
# Should return: HTTP/2 200 OK
```

#### Option C: Restart PostgREST (Supabase Support)

If manual reload fails (Supabase-managed PostgREST):

1. **Contact Supabase Support**: support@supabase.com
2. **Provide Details**:
   - Project ID: `iaketsyhmqbwaabgykux`
   - Error: `PGRST002 - schema cache stale`
   - Recent migrations applied: `<list migration files>`
3. **Request**: PostgREST pod restart

**Expected Outcome**: Supabase support restarts PostgREST within 1 hour.

#### Option D: Clear Browser Cache (User-Side)

If only affecting some users (stale frontend cache):

```bash
# Hard refresh
Ctrl+Shift+R (Windows/Linux)
Cmd+Shift+R (Mac)

# Or clear site data
Chrome DevTools > Application > Clear Storage > Clear Site Data
```

### Escalation

If PGRST002 persists > 30 minutes:

1. **Check Supabase Status**: https://status.supabase.com
2. **Review Schema Changes**: Rollback recent migration if suspect
3. **Contact Supabase Support**: Include project ID and error logs

---

## Procedure: Force Re-ingest

**Use Case**: When a batch was rejected due to transient error (e.g., DB timeout) and needs to be retried without re-uploading the file.

### Preconditions

- Original CSV file is still in storage (`gs://dragonfly-intake/batches/<BATCH_ID>.csv`)
- Batch status is `failed` or `completed` (cannot re-ingest `processing` batches)

### Steps

#### Step 1: Identify Batch ID

```bash
# Query recent failed batches
psql $SUPABASE_DB_URL -c "
SELECT
    id,
    filename,
    status,
    rejection_reason,
    created_at
FROM intake.simplicity_batches
WHERE status = 'failed'
ORDER BY created_at DESC
LIMIT 10;
"
```

#### Step 2: Reset Batch to 'uploaded' State

```sql
-- Reset batch (worker will auto-reprocess)
UPDATE intake.simplicity_batches
SET
    status = 'uploaded',
    rejection_reason = NULL,
    updated_at = NOW()
WHERE id = '<BATCH_ID>';
```

#### Step 3: Monitor Reprocessing

```bash
# Watch batch status in real-time
watch -n 2 "psql $SUPABASE_DB_URL -c \"
SELECT
    id,
    status,
    row_count_inserted,
    row_count_invalid,
    updated_at
FROM intake.simplicity_batches
WHERE id = '<BATCH_ID>';
\""

# Or use Sentinel
SUPABASE_MODE=prod python -m backend.workers.sentinel --loop --interval 10
```

### Expected Timeline

| Time  | Status       | Notes                           |
| ----- | ------------ | ------------------------------- |
| T+0s  | `uploaded`   | Batch reset, waiting for worker |
| T+30s | `staging`    | Worker picked up batch          |
| T+1m  | `validating` | Parsing CSV, validating rows    |
| T+2m  | `inserting`  | Writing valid rows to DB        |
| T+3m  | `completed`  | Success!                        |

### Troubleshooting

**If batch stuck in 'validating' > 5 minutes**:

- Check logs: `tail -f /var/log/dragonfly/worker.log`
- Likely issue: Large file (>50K rows), increase timeout

**If batch fails again with same error**:

- Issue is NOT transient - review rejection reason
- Download error CSV, fix source data, re-upload

---

## Procedure: Manual Batch Cleanup

**Use Case**: Remove test/duplicate batches from the database.

### ⚠️ WARNING

**Destructive Operation**: This deletes batch records and associated row errors. Cannot be undone.

### Steps

#### Step 1: Identify Batches to Delete

```sql
-- List test batches (example: filename contains 'test')
SELECT
    id,
    filename,
    status,
    row_count_total,
    created_at
FROM intake.simplicity_batches
WHERE filename ILIKE '%test%'
ORDER BY created_at DESC;
```

#### Step 2: Delete Batch Records

```sql
-- Delete batch and cascade to row_errors (FK constraint)
DELETE FROM intake.simplicity_batches
WHERE id = '<BATCH_ID>';

-- Verify deletion
SELECT count(*)
FROM intake.simplicity_batches
WHERE id = '<BATCH_ID>';
-- Should return: 0
```

#### Step 3: Clean Up Storage (Optional)

```bash
# Delete CSV from Google Cloud Storage
gsutil rm gs://dragonfly-intake/batches/<BATCH_ID>.csv

# Or Supabase Storage (if using)
curl -X DELETE "https://iaketsyhmqbwaabgykux.supabase.co/storage/v1/object/intake-batches/<BATCH_ID>.csv" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY"
```

### Bulk Deletion

**Delete all test batches from last 7 days**:

```sql
DELETE FROM intake.simplicity_batches
WHERE filename ILIKE '%test%'
  AND created_at >= NOW() - INTERVAL '7 days';

-- Check how many rows will be deleted (DRY RUN):
SELECT count(*)
FROM intake.simplicity_batches
WHERE filename ILIKE '%test%'
  AND created_at >= NOW() - INTERVAL '7 days';
```

---

## Alert Routing

### CRITICAL Alerts (Immediate Action Required)

**Where CRITICAL alerts go:**

| Source               | Destination                  | Response SLA |
| -------------------- | ---------------------------- | ------------ |
| GitHub Actions       | Workflow fails → email       | 15 minutes   |
| Sentinel JSON output | Slack: **#dragonfly-alerts** | 15 minutes   |
| Manual escalation    | Slack: **#dragonfly-oncall** | Immediate    |

**What triggers CRITICAL:**

- Stuck batches (> 10 minutes in processing state)
- PGRST002 auto-reload failure
- Error rate spike > 50% in window

**On-call response commands:**

```bash
# Check current status
SUPABASE_MODE=prod python -m backend.workers.sentinel --json

# Manual schema cache reload
SUPABASE_MODE=prod python -m tools.pgrst_reload

# Check for stuck batches
SUPABASE_MODE=prod python -m tools.doctor --env prod
```

### WARNING Alerts (Monitor & Review)

| Source               | Destination                 | Response SLA |
| -------------------- | --------------------------- | ------------ |
| Sentinel JSON output | Logged for daily review     | 24 hours     |
| GitHub Actions       | Workflow succeeds (no fail) | N/A          |

**What triggers WARNING:**

- PGRST002 detected but auto-reload succeeded
- Error rate between 10-50%
- Approaching thresholds

### Future Alert Integrations (Roadmap)

| Integration     | Status  | Target Date |
| --------------- | ------- | ----------- |
| Discord webhook | Planned | Q1 2025     |
| PagerDuty       | Roadmap | Q2 2025     |
| SMS (Twilio)    | Roadmap | Q2 2025     |

---

## Emergency Contacts

| Role                 | Contact                    | Availability    |
| -------------------- | -------------------------- | --------------- |
| **On-Call Engineer** | Slack: #dragonfly-oncall   | 24/7            |
| **Backend Lead**     | backend-lead@dragonfly.com | M-F 9am-6pm ET  |
| **Database Admin**   | dba@dragonfly.com          | M-F 9am-6pm ET  |
| **Supabase Support** | support@supabase.com       | 24/7 (Pro Plan) |

### Escalation Path

1. **Level 1 - Ops Team**: Attempt resolution using this runbook (30 min)
2. **Level 2 - Engineering**: Slack #dragonfly-alerts with incident details
3. **Level 3 - Leadership**: Notify CTO if revenue-impacting (> 2 hours downtime)

---

## Appendix: Useful SQL Queries

### Check Pipeline Status

```sql
-- Summary of all batches by status
SELECT
    status,
    count(*) AS batch_count,
    sum(row_count_total) AS total_rows,
    sum(row_count_inserted) AS inserted_rows,
    sum(row_count_invalid) AS error_rows
FROM intake.simplicity_batches
GROUP BY status
ORDER BY status;
```

### Find Batches by Date Range

```sql
SELECT
    id,
    filename,
    status,
    row_count_total,
    row_count_inserted,
    created_at
FROM intake.simplicity_batches
WHERE created_at::date = CURRENT_DATE
ORDER BY created_at DESC;
```

### Top Plaintiffs by Judgment Count

```sql
SELECT
    plaintiff_name,
    count(*) AS judgment_count,
    sum(amount) AS total_amount
FROM public.judgments
GROUP BY plaintiff_name
ORDER BY judgment_count DESC
LIMIT 20;
```

### Recent Failed Batches with Errors

```sql
SELECT
    sb.id,
    sb.filename,
    sb.rejection_reason,
    sb.created_at,
    count(re.id) AS error_count
FROM intake.simplicity_batches sb
LEFT JOIN intake.row_errors re ON re.batch_id = sb.id
WHERE sb.status = 'failed'
  AND sb.created_at >= NOW() - INTERVAL '7 days'
GROUP BY sb.id, sb.filename, sb.rejection_reason, sb.created_at
ORDER BY sb.created_at DESC;
```

---

## Changelog

| Date       | Version | Changes                                                                       |
| ---------- | ------- | ----------------------------------------------------------------------------- |
| 2025-01-08 | 1.1     | Added Alert Routing section with CRITICAL/WARNING response SLAs               |
| 2025-01-04 | 1.0     | Initial release - covers batch stuck, error spikes, PGRST002, force re-ingest |

---

**End of Runbook**
