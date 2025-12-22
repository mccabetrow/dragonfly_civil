# Reaper & CEO Dashboard Runbook

> **Purpose**: How to verify the reaper is running and interpret CEO Dashboard metrics.

## Quick Reference

| Metric            | Healthy  | Warning   | Critical |
| ----------------- | -------- | --------- | -------- |
| Stuck Jobs        | 0        | -         | > 0      |
| Pending Jobs      | < 50     | 50-100    | > 100    |
| Active Workers    | ≥ 1      | -         | 0        |
| Reaper Last Run   | < 15 min | 15-30 min | > 30 min |
| Failed Jobs (24h) | < 10     | 10-50     | > 50     |

---

## 1. Verify Reaper is Running

### Option A: Run Diagnostic SQL

Run the diagnostic script in pgAdmin or psql:

```sql
-- File: ops/reaper_health.sql
\i ops/reaper_health.sql
```

Or run individual checks:

```sql
-- CHECK 1: Is the reaper scheduled?
SELECT jobid, jobname, schedule, active
FROM cron.job
WHERE jobname IN ('dragonfly_reaper', 'reap_stuck_jobs');

-- Expected: 1 row with active = true

-- CHECK 2: Recent execution history
SELECT jrd.status, jrd.start_time, jrd.end_time, jrd.return_message
FROM cron.job_run_details jrd
JOIN cron.job j ON j.jobid = jrd.jobid
WHERE j.jobname IN ('dragonfly_reaper', 'reap_stuck_jobs')
ORDER BY jrd.start_time DESC
LIMIT 5;

-- Expected: Recent entries with status = 'succeeded'

-- CHECK 3: Any stuck jobs right now?
SELECT COUNT(*) AS stuck_count
FROM ops.job_queue
WHERE status = 'processing'
  AND started_at < NOW() - INTERVAL '15 minutes';

-- Expected: 0 (if reaper is working)
```

### Option B: Use the API Endpoint

```powershell
# From local dev
.\scripts\load_env.ps1 -Mode dev
$response = Invoke-RestMethod -Uri "http://localhost:8000/api/health/system"
$response | ConvertTo-Json -Depth 5

# Check reaper status
$response.reaper_health

# Check for stuck jobs
$response.queue_health.stuck
```

### Option C: Use the Watchdog

```powershell
# Run once and check results
python -m backend.workers.watchdog --once --verbose
```

---

## 2. Interpret CEO Dashboard Metrics

### 2.1 Overall Status Colors

| Color     | Status   | Action Required                 |
| --------- | -------- | ------------------------------- |
| 🟢 Green  | Healthy  | None - all systems operational  |
| 🟡 Yellow | Degraded | Monitor - check warning metrics |
| 🔴 Red    | Critical | Immediate action required       |

### 2.2 Individual Metrics

#### Stuck Jobs

```
What it means: Jobs that started processing but never completed
Threshold: CRITICAL if > 0
Root causes:
  - Worker crashed during processing
  - Worker lost database connection
  - Job timeout too short for operation

Fix:
  1. Check worker logs for crashes
  2. Verify reaper is running (see Section 1)
  3. If reaper is running, jobs will auto-retry
  4. If reaper is NOT running, manually reset stuck jobs:
```

```sql
-- Manual reset (use sparingly)
UPDATE ops.job_queue
SET status = 'pending',
    started_at = NULL,
    locked_at = NULL,
    worker_id = NULL,
    last_error = 'Manual reset - stuck job recovery'
WHERE status = 'processing'
  AND started_at < NOW() - INTERVAL '30 minutes';
```

#### Active Workers

```
What it means: Workers that sent a heartbeat in the last 5 minutes
Threshold: CRITICAL if 0

If no active workers:
  1. Check Railway/Render logs for worker process
  2. Verify worker is deployed and running
  3. Check database connectivity from worker

Start worker locally:
```

```powershell
.\scripts\load_env.ps1 -Mode dev
python -m backend.workers.ingest_processor
```

#### Pending Jobs

```
What it means: Jobs waiting to be processed
Threshold: WARNING if > 50, CRITICAL if > 100

If high pending count:
  1. Scale up workers (add more instances)
  2. Check if workers are processing (active_workers > 0)
  3. Look for failed jobs (might be retrying repeatedly)
```

#### Failed Jobs (24h)

```
What it means: Jobs that exceeded max_attempts and went to DLQ
Threshold: WARNING if > 20

To investigate failed jobs:
```

```sql
SELECT id, job_type, last_error, attempts, created_at, updated_at
FROM ops.job_queue
WHERE status = 'failed'
  AND updated_at > NOW() - INTERVAL '24 hours'
ORDER BY updated_at DESC
LIMIT 20;
```

---

## 3. Common Scenarios

### Scenario: Dashboard Shows "Critical - Stuck Jobs"

```
1. Verify reaper is scheduled:
   SELECT * FROM cron.job WHERE jobname LIKE '%reaper%';

2. If no schedule exists, the reaper migration hasn't run.
   Check: supabase/migrations/20251220200001_queue_hardening.sql

3. If schedule exists but jobs are stuck:
   - Check cron.job_run_details for failed runs
   - Check reaper function permissions
   - Try running reaper manually:
```

```sql
SELECT * FROM ops.reap_stuck_jobs(15);  -- 15 min timeout
```

### Scenario: Dashboard Shows "Critical - No Active Workers"

```
1. Check Railway/Render dashboard for worker status
2. Check worker logs for startup errors
3. Verify DATABASE_URL is correct in production

4. Test database connectivity:
```

```powershell
.\scripts\load_env.ps1 -Mode prod
python -c "from backend.db import get_sync_connection; print(get_sync_connection())"
```

### Scenario: Dashboard Shows "Warning - High Pending Count"

```
1. Check if workers are running (active_workers should be > 0)
2. Check job processing rate:
```

```sql
SELECT
    date_trunc('hour', updated_at) AS hour,
    COUNT(*) FILTER (WHERE status = 'completed') AS completed,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed
FROM ops.job_queue
WHERE updated_at > NOW() - INTERVAL '24 hours'
GROUP BY 1
ORDER BY 1 DESC;
```

---

## 4. Monitoring Setup

### Discord Alerts (via Watchdog)

The watchdog can send alerts to Discord when metrics breach thresholds:

```powershell
# Set up webhook
$env:DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."

# Run continuously (in production, deploy as a separate worker)
python -m backend.workers.watchdog --interval 60
```

### n8n Integration

Create an n8n workflow that:

1. Calls `GET /api/health/system` every 5 minutes
2. Checks `overall_status`
3. If `critical`, send Discord/Slack notification

---

## 5. Health Endpoint Reference

### GET /api/health/system

Returns comprehensive SLO metrics:

```json
{
  "overall_status": "healthy",
  "timestamp": "2025-01-15T10:30:00Z",
  "environment": "production",
  "metrics": [
    {
      "name": "stuck_jobs",
      "status": "healthy",
      "value": 0,
      "threshold": "0",
      "message": "No stuck jobs"
    },
    {
      "name": "pending_jobs",
      "status": "healthy",
      "value": 12,
      "threshold": "100",
      "message": "12 pending jobs"
    },
    {
      "name": "active_workers",
      "status": "healthy",
      "value": 2,
      "threshold": "1",
      "message": "2 active worker(s)"
    },
    {
      "name": "reaper",
      "status": "healthy",
      "value": 3,
      "threshold": "15",
      "message": "Reaper ran 3 min ago"
    }
  ],
  "queue_health": {
    "pending": 12,
    "processing": 1,
    "failed": 3,
    "stuck": 0,
    "failed_24h": 5
  },
  "worker_health": {
    "total_workers": 2,
    "active_workers": 2,
    "last_heartbeat": "2025-01-15T10:29:30Z"
  },
  "reaper_health": {
    "last_status": "succeeded",
    "last_run": "2025-01-15T10:27:00Z",
    "return_message": null
  }
}
```

---

## 6. Related Documentation

- [ops/reaper_health.sql](../ops/reaper_health.sql) - Diagnostic SQL queries
- [backend/workers/watchdog.py](../backend/workers/watchdog.py) - Alerting worker
- [20251220200001_queue_hardening.sql](../supabase/migrations/20251220200001_queue_hardening.sql) - Reaper implementation
