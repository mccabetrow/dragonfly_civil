# Dragonfly Civil – Operational Troubleshooting Playbook

> **Battle-Ready Runbook:** Copy-paste commands for the 3 most critical failure scenarios.

---

## 1. Scenario: Worker Death (Heartbeat Failure)

### Trigger

`/api/v1/system/status` reports `enforcement_status: "offline"` or `ingest_status: "offline"`.

The `ops.v_system_health` view marks a worker offline when its last heartbeat is > 60 seconds old.

---

### Step 1: Check Railway Logs for OOM (Out of Memory)

```bash
# Via Railway CLI (replace SERVICE_ID with the actual service)
railway logs --service dragonfly-api --tail 100 | grep -i "oom\|killed\|memory"

# Enforcement worker
railway logs --service enforcement-worker --tail 100 | grep -i "oom\|killed\|memory"

# Ingest worker
railway logs --service ingest-worker --tail 100 | grep -i "oom\|killed\|memory"
```

**Railway Web UI Alternative:**

1. Go to [railway.app](https://railway.app) → Your Project
2. Click the failing service (e.g., `enforcement-worker`)
3. View **Logs** tab → Search for `OOM`, `Killed`, `MemoryError`

---

### Step 2: Restart the Worker Service

**Railway CLI:**

```bash
# Restart enforcement worker
railway up --service enforcement-worker --detach

# Restart ingest worker
railway up --service ingest-worker --detach
```

**Railway Web UI:**

1. Navigate to the service in Railway dashboard
2. Click **Settings** → **Restart** (or redeploy)
3. Confirm and monitor logs for successful startup

**PowerShell (Local Dev):**

```powershell
# Restart enforcement worker locally
.\.venv\Scripts\python.exe -m backend.workers.enforcement_engine

# Restart ingest worker locally
.\.venv\Scripts\python.exe -m backend.workers.ingest_processor
```

---

### Step 3: Reset Locked Jobs in Queue

Jobs that were being processed when the worker died will be stuck with `locked_at` set.
Reset them so they can be picked up again:

```sql
-- View stuck jobs (locked > 5 minutes ago, still 'processing')
SELECT id, job_type, status, locked_at, attempts, last_error
FROM ops.job_queue
WHERE status = 'processing'
  AND locked_at < now() - INTERVAL '5 minutes'
ORDER BY locked_at ASC;

-- Reset stuck jobs to 'pending' for retry
UPDATE ops.job_queue
SET status = 'pending',
    locked_at = NULL,
    updated_at = now()
WHERE status = 'processing'
  AND locked_at < now() - INTERVAL '5 minutes';

-- Check if jobs are now ready for pickup
SELECT id, job_type, status, attempts
FROM ops.job_queue
WHERE status = 'pending'
ORDER BY created_at ASC
LIMIT 10;
```

**Run via PowerShell:**

```powershell
$env:SUPABASE_MODE='prod'
.\.venv\Scripts\python.exe -c @"
import psycopg
from src.supabase_client import get_supabase_db_url

sql = '''
UPDATE ops.job_queue
SET status = 'pending',
    locked_at = NULL,
    updated_at = now()
WHERE status = 'processing'
  AND locked_at < now() - INTERVAL '5 minutes'
RETURNING id, job_type;
'''

with psycopg.connect(get_supabase_db_url()) as conn:
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
        conn.commit()
        print(f'Reset {len(rows)} stuck jobs: {rows}')
"@
```

---

### Step 4: Verify Worker Recovery

```powershell
# Check system health
$env:SUPABASE_MODE='prod'
.\.venv\Scripts\python.exe -m tools.doctor --env prod

# Or query the view directly
.\.venv\Scripts\python.exe -c @"
import psycopg
from src.supabase_client import get_supabase_db_url

with psycopg.connect(get_supabase_db_url()) as conn:
    with conn.cursor() as cur:
        cur.execute('SELECT * FROM ops.v_system_health')
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
        print(dict(zip(cols, row)))
"@
```

Expected output: `ingest_status: 'online'`, `enforcement_status: 'online'`

---

## 2. Scenario: Migration Block (Deployment Stuck)

### Trigger

Deployment fails during `supabase migration up` or `db_push.ps1` with errors like:

- `migration already applied`
- `relation already exists`
- Lock timeout

---

### Step 1: Check Migration Status

```sql
-- Check which migrations are recorded
SELECT version, name, executed_at
FROM public.v_migration_status
ORDER BY executed_at DESC
LIMIT 20;

-- Check Supabase's internal migration table
SELECT version, name, statements_applied_successfully
FROM supabase_migrations.schema_migrations
ORDER BY version DESC
LIMIT 20;
```

**PowerShell:**

```powershell
$env:SUPABASE_MODE='prod'
.\.venv\Scripts\python.exe -m tools.migration_status --env prod
```

---

### Step 2: Force-Unlock Migration Table

If a migration is stuck mid-apply (e.g., from a crashed deploy), the advisory lock may still be held.

```sql
-- Check for advisory locks on migrations
SELECT pid, locktype, mode, granted
FROM pg_locks
WHERE locktype = 'advisory';

-- Terminate blocking sessions (⚠️ DANGER - use with caution)
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
  AND state = 'idle in transaction'
  AND query LIKE '%schema_migrations%';
```

---

### Step 3: Mark Stuck Migration as Applied (Skip)

If a migration partially applied and cannot be re-run:

```bash
# Using Supabase CLI - mark migration as applied without running it
supabase migration repair --status applied <MIGRATION_VERSION>

# Example:
supabase migration repair --status applied 20251226000000
```

**PowerShell (via db_push):**

```powershell
# Use the repair mode in db_push.ps1
$env:SUPABASE_MODE='prod'
supabase migration repair --status applied 20251226000000 --db-url $env:SUPABASE_DB_URL_PROD
```

---

### Step 4: Emergency Rollback SQL

If a bad migration needs to be undone manually:

```sql
-- ⚠️ EMERGENCY ONLY - Manual rollback template

-- Step 1: Identify the bad migration
SELECT version, name FROM supabase_migrations.schema_migrations
WHERE version = '20251226000000';

-- Step 2: Remove the migration record (allows re-running or skipping)
DELETE FROM supabase_migrations.schema_migrations
WHERE version = '20251226000000';

-- Step 3: Manually reverse the changes
-- (Replace with actual rollback statements for the specific migration)
DROP VIEW IF EXISTS ops.v_live_feed_events;
DROP TABLE IF EXISTS some_new_table;
-- etc.

-- Step 4: Verify
SELECT version, name FROM supabase_migrations.schema_migrations
ORDER BY version DESC LIMIT 5;
```

**CAUTION:** Never edit migrations that have been applied to production. Create a new migration to fix issues instead.

---

## 3. Scenario: Simplicity API Down (Vendor Failure)

### Trigger

`ingest_worker` logs show repeated 500 errors from Simplicity API:

```
ERROR: Simplicity API returned 500: Internal Server Error
ERROR: HTTPSConnectionPool: Max retries exceeded
```

---

### Step 1: Pause the Ingestion Queue

Stop the worker from hammering a broken API:

```sql
-- View pending ingest jobs
SELECT id, job_type, status, created_at, payload->>'source' AS source
FROM ops.job_queue
WHERE job_type = 'ingest'
  AND status IN ('pending', 'processing')
ORDER BY created_at ASC;

-- Pause all pending ingest jobs
UPDATE ops.job_queue
SET status = 'paused',
    last_error = 'Manually paused: Simplicity API down',
    updated_at = now()
WHERE job_type = 'ingest'
  AND status = 'pending';

-- Verify paused
SELECT status, COUNT(*)
FROM ops.job_queue
WHERE job_type = 'ingest'
GROUP BY status;
```

**PowerShell:**

```powershell
$env:SUPABASE_MODE='prod'
.\.venv\Scripts\python.exe -c @"
import psycopg
from src.supabase_client import get_supabase_db_url

sql = '''
UPDATE ops.job_queue
SET status = 'paused',
    last_error = 'Manually paused: Simplicity API down',
    updated_at = now()
WHERE job_type = 'ingest'
  AND status = 'pending'
RETURNING id;
'''

with psycopg.connect(get_supabase_db_url()) as conn:
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
        conn.commit()
        print(f'Paused {len(rows)} ingest jobs')
"@
```

---

### Step 2: Enable Offline Mode (Feature Flag)

Set environment variable to skip Simplicity API calls:

**Railway:**

1. Go to Railway dashboard → `ingest-worker` service
2. Click **Variables** tab
3. Add: `SIMPLICITY_OFFLINE_MODE=true`
4. Service will auto-restart

**Local Dev (PowerShell):**

```powershell
$env:SIMPLICITY_OFFLINE_MODE='true'
.\.venv\Scripts\python.exe -m backend.workers.ingest_processor
```

**In Code (if not yet implemented):**

```python
# Add to backend/workers/ingest_processor.py at the top:
import os
SIMPLICITY_OFFLINE_MODE = os.getenv("SIMPLICITY_OFFLINE_MODE", "").lower() == "true"

# Then in the Simplicity API call:
if SIMPLICITY_OFFLINE_MODE:
    logger.warning("SIMPLICITY_OFFLINE_MODE enabled - skipping API call")
    return None
```

---

### Step 3: Resume Queue When API Recovers

```sql
-- Test Simplicity API is back (do this manually first!)
-- Then resume paused jobs:

UPDATE ops.job_queue
SET status = 'pending',
    last_error = NULL,
    updated_at = now()
WHERE job_type = 'ingest'
  AND status = 'paused';

-- Verify resumed
SELECT status, COUNT(*)
FROM ops.job_queue
WHERE job_type = 'ingest'
GROUP BY status;
```

**PowerShell:**

```powershell
$env:SUPABASE_MODE='prod'
.\.venv\Scripts\python.exe -c @"
import psycopg
from src.supabase_client import get_supabase_db_url

sql = '''
UPDATE ops.job_queue
SET status = 'pending',
    last_error = NULL,
    updated_at = now()
WHERE job_type = 'ingest'
  AND status = 'paused'
RETURNING id;
'''

with psycopg.connect(get_supabase_db_url()) as conn:
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
        conn.commit()
        print(f'Resumed {len(rows)} ingest jobs')
"@
```

---

### Step 4: Disable Offline Mode

1. Remove `SIMPLICITY_OFFLINE_MODE` from Railway variables
2. Service auto-restarts
3. Monitor logs for successful API calls

---

## 4. Release Gate: Pre-Deployment Validation

The release gate (`tools/prod_gate.py`) is a comprehensive pre-deployment check system with two modes:

### Gate Modes

| Mode   | Purpose                         | When to Use                  |
| ------ | ------------------------------- | ---------------------------- |
| `dev`  | Local correctness (tests, lint) | Before committing, local dev |
| `prod` | Strict production blockers      | Before deploying to Railway  |

### Running the Release Gate

**Dev Mode (Local Correctness):**

```powershell
# Full dev gate
$env:SUPABASE_MODE='dev'
python -m tools.prod_gate --mode dev

# Skip slow checks
python -m tools.prod_gate --mode dev --skip pytest evaluator
```

**Prod Mode (Deployment Readiness):**

```powershell
# Full prod gate (requires prod credentials)
$env:SUPABASE_MODE='prod'
python -m tools.prod_gate --mode prod

# JSON output for CI/CD
python -m tools.prod_gate --mode prod --json
```

### Check Reference

| Check             | Dev Mode | Prod Mode | What It Validates                   |
| ----------------- | -------- | --------- | ----------------------------------- |
| PyTest Suite      | ✅       | ❌        | All tests pass                      |
| Import Graph      | ✅       | ❌        | Key modules import without error    |
| Lint (Ruff)       | ✅       | ❌        | No critical syntax errors           |
| AI Evaluator      | ✅       | ✅        | ≥95% pass rate on golden dataset    |
| API Health        | ❌       | ✅        | /api/health returns 200 OK          |
| Worker Heartbeats | ❌       | ✅        | Workers online in last 5 minutes    |
| DB Connectivity   | ✅       | ✅        | Database reachable, tables exist    |
| Migration Status  | ⚠️       | ✅        | No pending migrations (warn in dev) |

### Troubleshooting Gate Failures

**"API Health failed: Connection failed"**

- Verify `DRAGONFLY_API_URL_PROD` env var is set correctly
- Check Railway API service is deployed and running
- Run: `curl https://dragonflycivil-production-d57a.up.railway.app/api/health`

**"Worker Heartbeats: No workers active in last 300s"**

- Workers may have crashed. Check Railway logs.
- Restart workers: Railway Dashboard → Service → Restart
- See [Scenario 1: Worker Death](#1-scenario-worker-death-heartbeat-failure)

**"Migration Status: N pending migration(s)"**

- Apply migrations before deploying:
  ```powershell
  ./scripts/db_push.ps1 -SupabaseEnv prod
  ```

**"DB Connectivity: Connection failed"**

- Check `SUPABASE_DB_URL` env var
- Verify database is not in maintenance mode
- Try: `python -m tools.doctor --env prod`

**"AI Evaluator: below 95% threshold"**

- Review failed cases in evaluator output
- Update golden dataset if legitimate model changes
- Do not deploy until evaluator passes

### Environment Variables

The release gate reads these env vars (no hardcoded URLs):

| Variable                 | Required | Purpose                          |
| ------------------------ | -------- | -------------------------------- |
| `SUPABASE_MODE`          | ✅       | Target environment (dev/prod)    |
| `DRAGONFLY_API_URL_PROD` | ⚪       | Prod API URL (has default)       |
| `DRAGONFLY_API_URL_DEV`  | ⚪       | Dev API URL (defaults localhost) |

---

## Quick Reference: Common SQL Snippets

```sql
-- System health at a glance
SELECT * FROM ops.v_system_health;

-- Worker heartbeat status
SELECT worker_id, worker_type, status, last_seen_at,
       CASE WHEN last_seen_at > now() - INTERVAL '60 seconds'
            THEN 'online' ELSE 'offline' END AS computed_status
FROM ops.worker_heartbeats
ORDER BY last_seen_at DESC;

-- Job queue summary
SELECT job_type::text, status::text, COUNT(*)
FROM ops.job_queue
GROUP BY job_type, status
ORDER BY job_type, status;

-- Failed jobs in last 24h
SELECT id, job_type, last_error, updated_at
FROM ops.job_queue
WHERE status = 'failed'
  AND updated_at > now() - INTERVAL '24 hours'
ORDER BY updated_at DESC;

-- Recent migrations
SELECT * FROM public.v_migration_status
ORDER BY executed_at DESC
LIMIT 10;
```

---

## Escalation Contacts

| Scenario        | First Responder  | Escalation     |
| --------------- | ---------------- | -------------- |
| Worker Death    | On-call engineer | Team lead      |
| Migration Block | Backend lead     | DBA            |
| Vendor API Down | On-call engineer | Vendor support |

---

_Last updated: 2025-12-17_
