# Production Incident Checklist

**Dragonfly Civil — Incident Response Playbook**

Use this checklist whenever a production issue is detected. Follow steps in order; do not skip unless explicitly noted.

---

## 1. Detection & Acknowledgment (< 5 min)

- [ ] **Identify the alert source**: Health endpoint failure, Railway log, n8n workflow, user report
- [ ] **Check health endpoints**:
  - `/api/health` — basic service up
  - `/api/health/db` — database connectivity (5s timeout)
  - `/api/health/supabase` — Supabase REST API (8s timeout)
  - `/api/health/ready` — combined readiness probe
- [ ] **Acknowledge the incident** in Slack/Discord with timestamp and brief description
- [ ] **Set severity**:
  - **P1 (Critical)**: Service fully down, data loss risk
  - **P2 (High)**: Core functionality degraded, users impacted
  - **P3 (Medium)**: Non-critical feature broken, workaround exists
  - **P4 (Low)**: Minor issue, no immediate user impact

---

## 2. Triage (< 10 min)

### 2.1 Quick Classification

Check for these error codes in logs (see [Error Taxonomy](#error-code-reference)):

| Symptom            | Likely Error Code | First Check                           |
| ------------------ | ----------------- | ------------------------------------- |
| Connection refused | `DFE-DB-001`      | Database pooler status                |
| Query timeout      | `DFE-DB-002`      | Long-running queries, pool exhaustion |
| Missing env var    | `DFE-CFG-001`     | Railway env configuration             |
| Invalid config     | `DFE-CFG-002`     | Config file syntax                    |
| HTTP timeout       | `DFE-NET-001`     | External service status               |
| Supabase 401/403   | `DFE-VND-001`     | API key validity                      |
| Auth token expired | `DFE-AUTH-001`    | Service role key                      |

### 2.2 Environment Check

```powershell
# Load environment
./scripts/load_env.ps1

# Check current env target
$env:SUPABASE_MODE  # Should be 'prod' for production

# Run doctor to validate schema
./.venv/Scripts/python.exe -m tools.doctor --env prod
```

### 2.3 Railway Logs

```bash
railway logs --environment production --tail 100
```

Look for:

- `ERROR` or `CRITICAL` log levels
- Error codes prefixed with `DFE-`
- Stack traces with file locations
- Timestamps indicating when issues started

---

## 3. Diagnosis (< 30 min)

### 3.1 Database Issues

```sql
-- Check active connections
SELECT count(*) FROM pg_stat_activity WHERE datname = current_database();

-- Find long-running queries (> 60s)
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state != 'idle'
  AND now() - pg_stat_activity.query_start > interval '60 seconds'
ORDER BY duration DESC;

-- Check for locks
SELECT blocked_locks.pid AS blocked_pid,
       blocking_locks.pid AS blocking_pid,
       blocked_activity.usename AS blocked_user,
       blocking_activity.usename AS blocking_user,
       blocked_activity.query AS blocked_statement
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

### 3.2 Worker Issues

Check worker heartbeats:

```sql
SELECT worker_name, last_heartbeat,
       EXTRACT(EPOCH FROM (now() - last_heartbeat)) AS seconds_since_heartbeat,
       status, jobs_processed, error_count
FROM ops.worker_heartbeats
WHERE last_heartbeat > now() - interval '1 hour'
ORDER BY last_heartbeat DESC;
```

If workers are stale (> 5 min since heartbeat):

- Check Railway deployment status
- Verify worker processes are running
- Check for OOM kills in Railway metrics

### 3.3 Supabase Issues

```powershell
# Test Supabase connectivity
./.venv/Scripts/python.exe -c "
from src.supabase_client import get_supabase_env, create_supabase_client
env = get_supabase_env()
client = create_supabase_client(env)
result = client.table('plaintiffs').select('id').limit(1).execute()
print(f'Supabase OK: {len(result.data)} row(s)')
"
```

If Supabase is down:

- Check [Supabase Status Page](https://status.supabase.com/)
- Verify API keys in Railway env vars
- Test from a different network

### 3.4 n8n Workflow Issues

```powershell
# Validate n8n flow configurations
./.venv/Scripts/python.exe -m tools.validate_n8n_flows --env prod
```

---

## 4. Resolution

### 4.1 Common Fixes

| Issue               | Fix                                                                              |
| ------------------- | -------------------------------------------------------------------------------- |
| **Pool exhausted**  | Restart worker pods; check for connection leaks                                  |
| **Worker crashed**  | Railway redeploy: `railway up --environment production`                          |
| **Stale cache**     | Clear PostgREST schema cache: `./.venv/Scripts/python.exe -m tools.pgrst_reload` |
| **Bad migration**   | Rollback: apply inverse migration, then re-push                                  |
| **Env var missing** | Add in Railway dashboard, redeploy                                               |
| **Rate limited**    | Reduce concurrency, add backoff in worker                                        |

### 4.2 Emergency Procedures

#### Disable Job Processing

```sql
-- Pause all pending jobs
UPDATE ops.job_queue SET status = 'paused' WHERE status = 'pending';
```

#### Force Worker Restart

```powershell
# In Railway
railway service restart --environment production
```

#### Schema Emergency Reload

```powershell
# Force PostgREST to reload schema
./.venv/Scripts/python.exe -m tools.pgrst_reload --env prod
```

---

## 5. Validation

After applying fixes:

- [ ] **Health checks green**: All `/api/health/*` endpoints return 200
- [ ] **Doctor passes**: `python -m tools.doctor --env prod`
- [ ] **Smoke test passes**: `python -m tools.smoke_plaintiffs --env prod`
- [ ] **View queries work**: Test dashboard views manually
- [ ] **Worker heartbeats resume**: Fresh entries in `ops.worker_heartbeats`

---

## 6. Post-Incident

### 6.1 Immediate (< 1 hour)

- [ ] **All-clear notification**: Update Slack/Discord with resolution
- [ ] **Document timeline**: When detected, when mitigated, when resolved
- [ ] **Preserve evidence**: Save relevant logs, screenshots, query results

### 6.2 Follow-up (< 24 hours)

- [ ] **Create incident report** (if P1/P2):

  - Summary of impact
  - Root cause analysis
  - Timeline of events
  - What worked / what didn't
  - Action items to prevent recurrence

- [ ] **File issues** for any discovered bugs or improvements
- [ ] **Update runbooks** if procedures were unclear or missing

---

## Error Code Reference

Error codes follow the pattern `DFE-{CATEGORY}-{NUMBER}`:

### Configuration Errors (DFE-CFG-\*)

| Code        | Description                  | Retryable |
| ----------- | ---------------------------- | --------- |
| DFE-CFG-001 | Missing environment variable | No        |
| DFE-CFG-002 | Invalid configuration value  | No        |
| DFE-CFG-003 | Configuration file not found | No        |

### Database Errors (DFE-DB-\*)

| Code       | Description                    | Retryable |
| ---------- | ------------------------------ | --------- |
| DFE-DB-001 | Database connection failed     | Yes       |
| DFE-DB-002 | Query timeout                  | Yes       |
| DFE-DB-003 | Transaction failed             | Yes       |
| DFE-DB-004 | Pool exhausted                 | Yes       |
| DFE-DB-005 | Integrity constraint violation | No        |

### Network Errors (DFE-NET-\*)

| Code        | Description           | Retryable |
| ----------- | --------------------- | --------- |
| DFE-NET-001 | HTTP request timeout  | Yes       |
| DFE-NET-002 | Connection refused    | Yes       |
| DFE-NET-003 | DNS resolution failed | Yes       |
| DFE-NET-004 | SSL/TLS error         | No        |

### Vendor Errors (DFE-VND-\*)

| Code        | Description         | Retryable          |
| ----------- | ------------------- | ------------------ |
| DFE-VND-001 | Supabase API error  | Yes                |
| DFE-VND-002 | Railway API error   | Yes                |
| DFE-VND-003 | n8n webhook error   | Yes                |
| DFE-VND-004 | Vendor rate limited | Yes (with backoff) |

### Authentication Errors (DFE-AUTH-\*)

| Code         | Description                  | Retryable |
| ------------ | ---------------------------- | --------- |
| DFE-AUTH-001 | Missing authentication token | No        |
| DFE-AUTH-002 | Invalid/expired token        | No        |
| DFE-AUTH-003 | Insufficient permissions     | No        |

### Validation Errors (DFE-VAL-\*)

| Code        | Description                 | Retryable |
| ----------- | --------------------------- | --------- |
| DFE-VAL-001 | Input validation failed     | No        |
| DFE-VAL-002 | Schema validation error     | No        |
| DFE-VAL-003 | Data integrity check failed | No        |

### Internal Errors (DFE-INT-\*)

| Code        | Description               | Retryable |
| ----------- | ------------------------- | --------- |
| DFE-INT-001 | Unexpected internal error | Maybe     |
| DFE-INT-002 | Resource exhausted        | Yes       |
| DFE-INT-003 | Operation cancelled       | Yes       |

---

## Quick Reference URLs

| Resource          | URL                           |
| ----------------- | ----------------------------- |
| Health (basic)    | `GET /api/health`             |
| Health (DB)       | `GET /api/health/db`          |
| Health (Supabase) | `GET /api/health/supabase`    |
| Readiness         | `GET /api/health/ready`       |
| Version           | `GET /api/health/version`     |
| Ops metrics       | `GET /api/health/ops`         |
| Supabase Status   | https://status.supabase.com/  |
| Railway Dashboard | https://railway.app/dashboard |

---

_Last updated: 2025-01-15_
_Maintainer: Dragonfly Engineering_
