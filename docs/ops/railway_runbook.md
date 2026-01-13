# Railway Deployment Runbook

**Dragonfly Civil – Production Deployment, Verification, and Recovery**

_Version 1.0 | December 2025_

---

## Table of Contents

1. [Service Overview](#service-overview)
2. [Required Environment Variables](#required-environment-variables)
3. [Start Commands](#start-commands)
4. [Pre-Deployment Checklist](#pre-deployment-checklist)
5. [Deployment Verification](#deployment-verification)
6. [Log Analysis](#log-analysis)
7. [Worker Scaling](#worker-scaling)
8. [Rollback Procedures](#rollback-procedures)
9. [Golden Path Validation](#golden-path-validation)
10. [Troubleshooting](#troubleshooting)

---

## Service Overview

| Service Name                   | Purpose                        | Process Type |
| ------------------------------ | ------------------------------ | ------------ |
| `dragonfly-api`                | FastAPI REST API               | web          |
| `dragonfly-worker-ingest`      | CSV ingestion & job processing | worker       |
| `dragonfly-worker-enforcement` | Enforcement calculations & AI  | worker       |

**Railway Project URL:** `https://railway.app/project/<PROJECT_ID>`

**Production API Base:** `https://dragonflycivil-production-d57a.up.railway.app`

---

## Required Environment Variables

### All Services (Common)

| Variable                    | Required | Example                                    | Notes                              |
| --------------------------- | -------- | ------------------------------------------ | ---------------------------------- |
| `SUPABASE_MODE`             | ✅       | `prod`                                     | Must be `prod` for production      |
| `ENVIRONMENT`               | ✅       | `prod`                                     | `dev`, `staging`, `prod`           |
| `SUPABASE_URL`              | ✅       | `https://xxx.supabase.co`                  | Supabase project URL               |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅       | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`  | 100+ character JWT                 |
| `SUPABASE_DB_URL`           | ✅       | `postgresql://postgres:...@...pooler:5432` | Use transaction pooler (port 5432) |

### dragonfly-api (Additional)

| Variable            | Required | Example          | Notes                  |
| ------------------- | -------- | ---------------- | ---------------------- |
| `PORT`              | Auto     | `8080`           | Injected by Railway    |
| `DRAGONFLY_API_KEY` | ✅       | `df_prod_xxx...` | API authentication key |

### dragonfly-worker-enforcement (Additional)

| Variable         | Required | Example  | Notes                   |
| ---------------- | -------- | -------- | ----------------------- |
| `OPENAI_API_KEY` | ✅       | `sk-...` | For AI agent operations |

### Variable Validation

Run this SQL to verify DB connectivity from Railway:

```sql
-- Verify connection works and role is correct
SELECT current_user, current_database(), now() AS server_time;

-- Verify schema access
SELECT schema_name FROM information_schema.schemata
WHERE schema_name IN ('public', 'ops', 'intake', 'enforcement')
ORDER BY schema_name;
```

---

## Start Commands

Configure in Railway → Service → Settings → Start Command:

### dragonfly-api

```bash
python -m tools.run_uvicorn
```

### dragonfly-worker-ingest

```bash
python -m backend.workers.ingest_processor
```

### dragonfly-worker-enforcement

```bash
python -m backend.workers.enforcement_engine
```

---

## Pre-Deployment Checklist

### Before Deploying

```text
□ Run local preflight checks
    powershell ./scripts/preflight_prod.ps1

□ Verify migrations are applied
    python -m tools.migration_status --env prod

□ Run security audit
    python -m tools.security_audit --env prod

□ Confirm no uncommitted changes
    git status

□ Tag the release
    git tag -a v1.x.x -m "Release v1.x.x"
    git push origin v1.x.x
```

### Database Migrations

Apply migrations BEFORE deploying new code:

```powershell
# From local machine with prod credentials
$env:SUPABASE_MODE = "prod"
./scripts/db_push.ps1 -SupabaseEnv prod
```

Verify migration was applied:

```sql
SELECT version, name, executed_at
FROM supabase_migrations.schema_migrations
ORDER BY version DESC
LIMIT 10;
```

---

## Deployment Verification

### Step 1: Confirm Git SHA

Railway injects `RAILWAY_GIT_COMMIT_SHA`. Verify deployed version:

**From Railway Dashboard:**

1. Go to Service → Deployments → Latest
2. Click deployment to see commit SHA

**From API Health Endpoint:**

```bash
curl -s https://dragonflycivil-production-d57a.up.railway.app/api/health | jq '.git_sha'
```

**From Worker Logs:**
Workers log their SHA at startup:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DRAGONFLY WORKER STARTING                        │
├─────────────────────────────────────────────────────────────────────┤
│  Worker ID:    ingest-abc123                                        │
│  Worker Type:  ingest_processor                                     │
│  Environment:  prod                                                 │
│  Git SHA:      a1b2c3d4                                             │
│  Python:       3.11.4                                               │
└─────────────────────────────────────────────────────────────────────┘
```

**Expected:** SHA matches the deployed commit.

### Step 2: API Health Check

```bash
# Basic health
curl -s https://dragonflycivil-production-d57a.up.railway.app/api/health

# Detailed health with DB check
curl -s https://dragonflycivil-production-d57a.up.railway.app/api/v1/intake/health
```

**Expected Response:**

```json
{
  "status": "ok",
  "environment": "prod",
  "git_sha": "a1b2c3d4",
  "db_connected": true,
  "timestamp": "2025-12-20T10:30:00Z"
}
```

### Step 3: Worker Heartbeat Check

```sql
-- Check workers are alive (within last 5 minutes)
SELECT
    worker_id,
    worker_type,
    status,
    last_heartbeat_at,
    EXTRACT(EPOCH FROM (now() - last_heartbeat_at)) AS seconds_since_heartbeat
FROM ops.worker_heartbeats
WHERE last_heartbeat_at > now() - interval '5 minutes'
ORDER BY last_heartbeat_at DESC;
```

**Expected:** At least one row per worker type with `status = 'running'`.

---

## Log Analysis

### Accessing Logs

**Railway Dashboard:**

1. Go to Project → Service → Logs
2. Use search to filter: `error`, `CRITICAL`, `claim_pending_job`

**Railway CLI:**

```bash
railway logs --service dragonfly-api
railway logs --service dragonfly-worker-ingest
railway logs --service dragonfly-worker-enforcement
```

### Key Log Patterns

#### DB Connectivity

**✅ Success:**

```
PostgreSQL connection established
Pool size: 5, max overflow: 10
```

**❌ Failure:**

```
FATAL: password authentication failed for user
Connection refused
```

#### Permissions

**✅ Success:**

```
claim_pending_job: claimed job abc123
update_job_status: job abc123 -> completed
```

**❌ Failure:**

```
permission denied for table ops.job_queue
ERROR: function ops.claim_pending_job does not exist
```

#### Job Claiming

**✅ Success:**

```
[ingest_processor] Claimed job: 123e4567-e89b-12d3-a456-426614174000
[ingest_processor] Processing batch: smoke-test-valid
[ingest_processor] Job completed: 123e4567-e89b-12d3-a456-426614174000
```

**❌ Failure:**

```
[ingest_processor] No pending jobs found (idle)
[ingest_processor] Job failed: InFailedSqlTransaction
[ingest_processor] CRITICAL: Crash loop detected after 10 failures
```

### Log Queries (SQL)

```sql
-- Recent intake log events
SELECT created_at, event_type, source_system, details
FROM ops.intake_logs
ORDER BY created_at DESC
LIMIT 20;

-- Failed jobs in last hour
SELECT id, job_type, status, error_message, updated_at
FROM ops.job_queue
WHERE status = 'failed'
  AND updated_at > now() - interval '1 hour'
ORDER BY updated_at DESC;

-- Worker health summary
SELECT
    worker_type,
    COUNT(*) AS active_workers,
    MAX(last_heartbeat_at) AS latest_heartbeat
FROM ops.worker_heartbeats
WHERE last_heartbeat_at > now() - interval '10 minutes'
GROUP BY worker_type;
```

---

## Worker Scaling

### Safe Scaling Procedure: 0 → 1 → N

#### Scale 0 → 1 (Initial Deployment)

1. **Deploy with replicas = 0** (service exists but not running)
2. **Verify database is ready:**
   ```sql
   SELECT COUNT(*) FROM ops.job_queue WHERE status = 'pending';
   ```
3. **Scale to 1 replica:**
   - Railway Dashboard → Service → Settings → Replicas → 1
   - Or: `railway service update --replicas 1`
4. **Watch logs for successful startup:**
   ```
   DRAGONFLY WORKER STARTING
   PostgreSQL connection established
   Entering main loop...
   ```
5. **Verify heartbeat appears:**
   ```sql
   SELECT * FROM ops.worker_heartbeats
   WHERE worker_type = 'ingest_processor'
   ORDER BY last_heartbeat_at DESC LIMIT 1;
   ```

#### Scale 1 → N (Horizontal Scaling)

⚠️ **Warning:** Workers use advisory locks for job claiming. Scaling is safe but monitor for contention.

1. **Ensure single worker is healthy:**

   ```sql
   SELECT worker_id, status, last_heartbeat_at
   FROM ops.worker_heartbeats
   WHERE status = 'running';
   ```

2. **Gradually increase replicas:**

   ```
   1 → 2 (wait 2 minutes, verify)
   2 → 3 (wait 2 minutes, verify)
   ```

3. **Monitor job throughput:**

   ```sql
   SELECT
       date_trunc('minute', updated_at) AS minute,
       COUNT(*) FILTER (WHERE status = 'completed') AS completed,
       COUNT(*) FILTER (WHERE status = 'failed') AS failed
   FROM ops.job_queue
   WHERE updated_at > now() - interval '10 minutes'
   GROUP BY 1
   ORDER BY 1 DESC;
   ```

4. **Watch for lock contention:**
   ```sql
   -- Check for waiting locks
   SELECT pid, wait_event_type, wait_event, state, query
   FROM pg_stat_activity
   WHERE application_name LIKE 'dragonfly%'
     AND wait_event IS NOT NULL;
   ```

#### Scale N → 0 (Shutdown)

1. **Stop queueing new jobs** (if applicable)
2. **Set replicas to 0:**
   - Railway Dashboard → Service → Settings → Replicas → 0
3. **Wait for graceful shutdown** (workers handle SIGTERM)
4. **Verify no orphaned jobs:**
   ```sql
   SELECT * FROM ops.job_queue
   WHERE status = 'processing'
     AND locked_at < now() - interval '5 minutes';
   ```

---

## Rollback Procedures

### Code Rollback (Railway)

1. **Identify last known good commit:**

   ```bash
   git log --oneline -10
   ```

2. **Rollback in Railway:**

   - Dashboard → Service → Deployments
   - Find the previous successful deployment
   - Click "Redeploy"

3. **Or force deploy previous commit:**

   ```bash
   # Reset to previous commit locally
   git reset --hard <GOOD_COMMIT_SHA>
   git push --force origin main
   ```

4. **Verify rollback:**
   ```bash
   curl -s https://dragonflycivil-production-d57a.up.railway.app/api/health | jq '.git_sha'
   ```

### Database Migration Rollback

⚠️ **Dangerous:** Only if you have a prepared rollback script.

1. **Stop all services first:**

   - Scale all workers to 0
   - Stop API if needed

2. **Apply rollback migration:**

   ```bash
   psql $SUPABASE_DB_URL -f supabase/migrations/<timestamp>_rollback.sql
   ```

3. **Verify schema state:**

   ```sql
   SELECT version, name FROM supabase_migrations.schema_migrations
   ORDER BY version DESC LIMIT 5;
   ```

4. **Restart services**

### Emergency: Disable Workers

If workers are causing damage, immediately scale to 0:

```bash
railway service update --service dragonfly-worker-ingest --replicas 0
railway service update --service dragonfly-worker-enforcement --replicas 0
```

Then investigate logs before restarting.

---

## Golden Path Validation

The golden path test validates the entire pipeline end-to-end.

### Running the Test

**Prerequisites:**

- API is deployed and healthy
- At least one ingest worker is running
- Test CSV exists: `data_in/simplicity_test_single.csv`

**Local execution against prod:**

```powershell
# Set prod credentials
$env:DRAGONFLY_API_BASE = "https://dragonflycivil-production-d57a.up.railway.app"
$env:DRAGONFLY_API_KEY = "<PROD_API_KEY>"

# Run golden path
./scripts/smoke_golden_path.ps1
```

**Expected output:**

```
[000000ms] [RUNNING] Health Check
[000150ms] [PASS] Health Check: API alive
[000160ms] [RUNNING] CSV Upload
[000800ms] [PASS] CSV Upload: batch_id = abc-123-def
[000810ms] [RUNNING] Ingest Poll
[015000ms] [PASS] Ingest Poll: Batch completed
[015010ms] [RUNNING] Snapshot
[015500ms] [PASS] Snapshot: Row counts valid

═══════════════════════════════════════════════════════════════════════
                           MISSION REPORT
═══════════════════════════════════════════════════════════════════════
  ✅ Health Check         PASS     150ms
  ✅ CSV Upload           PASS     640ms
  ✅ Ingest Poll          PASS   14190ms
  ✅ Snapshot             PASS     490ms
───────────────────────────────────────────────────────────────────────
  OVERALL: PASS          Total: 15480ms
═══════════════════════════════════════════════════════════════════════
```

### SQL Verification Queries

Run these after golden path to confirm data integrity:

```sql
-- 1. Verify batch was created
SELECT id, status, source_system, created_at
FROM intake.simplicity_batches
WHERE created_at > now() - interval '10 minutes'
ORDER BY created_at DESC
LIMIT 5;

-- 2. Verify raw rows were stored
SELECT batch_id, COUNT(*) AS row_count,
       COUNT(*) FILTER (WHERE status = 'validated') AS validated,
       COUNT(*) FILTER (WHERE status = 'failed') AS failed
FROM intake.simplicity_raw_rows
WHERE created_at > now() - interval '10 minutes'
GROUP BY batch_id;

-- 3. Verify job completed
SELECT id, job_type, status, result, updated_at
FROM ops.job_queue
WHERE job_type = 'simplicity_ingest'
  AND updated_at > now() - interval '10 minutes'
ORDER BY updated_at DESC
LIMIT 5;

-- 4. Verify no dangerous grants exist (security check)
SELECT grantee, table_name, privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'ops'
  AND grantee IN ('authenticated', 'anon')
  AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE');
-- Expected: 0 rows

-- 5. Verify worker heartbeats are fresh
SELECT worker_id, worker_type, status,
       EXTRACT(EPOCH FROM (now() - last_heartbeat_at))::int AS seconds_ago
FROM ops.worker_heartbeats
WHERE last_heartbeat_at > now() - interval '5 minutes';
```

### Automated Prod Gate

For comprehensive pre-deploy validation:

```powershell
$env:SUPABASE_MODE = "prod"
python -m tools.prod_gate --env prod --strict
```

This runs:

1. API health check
2. Database connectivity
3. Schema consistency
4. Worker heartbeat verification
5. Security audit

---

## Troubleshooting

### Common Issues

| Symptom                       | Likely Cause                    | Resolution                                  |
| ----------------------------- | ------------------------------- | ------------------------------------------- |
| API returns 503               | Service starting/crashed        | Check logs, wait 30s, redeploy              |
| Workers not claiming jobs     | DB permission issue             | Verify SUPABASE_DB_URL, check grants        |
| `InFailedSqlTransaction`      | Mid-transaction error           | Worker auto-recovers; check for data issues |
| `permission denied for table` | Wrong role in connection string | Use pooler URL, verify dragonfly_app grants |
| Crash loop detected           | 10 consecutive failures         | Check logs, fix root cause, redeploy        |
| Heartbeat stale               | Worker crashed without cleanup  | Scale to 0, wait, scale to 1                |

### Debug Commands

```bash
# Check Railway service status
railway status

# View environment variables (masked)
railway variables list

# SSH into running container
railway shell

# Inside container, test DB connection
python -c "from src.supabase_client import get_supabase_db_url; import psycopg; psycopg.connect(get_supabase_db_url()).close(); print('OK')"
```

### Escalation Path

1. **Check logs first** – 80% of issues visible in logs
2. **Run doctor** – `python -m tools.doctor --env prod`
3. **Check Supabase dashboard** – Database → Logs, Auth → Logs
4. **Rollback if needed** – See [Rollback Procedures](#rollback-procedures)
5. **Contact on-call** – Slack #dragonfly-incidents

---

## Quick Reference

```text
┌────────────────────────────────────────────────────────────────────┐
│                    RAILWAY QUICK COMMANDS                          │
├────────────────────────────────────────────────────────────────────┤
│  View logs:      railway logs --service <name>                     │
│  Redeploy:       railway redeploy --service <name>                 │
│  Scale:          railway service update --replicas N               │
│  Variables:      railway variables list                            │
│  Shell:          railway shell                                     │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│                    HEALTH CHECK URLS                               │
├────────────────────────────────────────────────────────────────────┤
│  API:            /api/health                                       │
│  Intake:         /api/v1/intake/health                             │
│  Metrics:        /api/v1/metrics (if enabled)                      │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│                    EMERGENCY PROCEDURES                            │
├────────────────────────────────────────────────────────────────────┤
│  Stop workers:   railway service update --replicas 0               │
│  Rollback:       Dashboard → Deployments → Redeploy previous       │
│  DB rollback:    psql $SUPABASE_DB_URL -f <rollback>.sql           │
└────────────────────────────────────────────────────────────────────┘
```

---

_Last updated: December 2025_
