# Dragonfly Production Incident Runbook

## Symptoms

- `connection refused` / `FATAL: too many connections`
- `permission denied for table/schema` or `RLS policy violation`
- `current transaction is aborted, commands ignored`
- Worker heartbeats stale (>5 min) or jobs stuck `in_progress`
- API returning 500s on `/health` or dashboard endpoints

---

## 1. Immediate Containment (< 2 min)

```powershell
# Scale workers to 0 to stop mutations
railway service update --name dragonfly-worker --replicas 0

# Verify deployed SHA matches expected
railway logs --service dragonfly-api | Select-String "version|sha|startup"

# If Railway unavailable, kill workers via DB
psql $SUPABASE_DB_URL -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name LIKE 'dragonfly%' AND state != 'idle';"
```

---

## 2. Diagnostics (SQL - run against prod)

```sql
-- Who am I? (expect: postgres, dragonfly_app, dragonfly_worker)
SELECT current_user, current_setting('role'), session_user;

-- RLS enabled on critical tables?
SELECT schemaname, tablename, rowsecurity FROM pg_tables
WHERE schemaname = 'public' AND tablename IN ('plaintiffs','judgments','jobs');

-- Current grants on public schema
SELECT grantee, privilege_type FROM information_schema.table_privileges
WHERE table_schema = 'public' ORDER BY grantee, privilege_type;

-- Active connections by role
SELECT usename, application_name, state, count(*)
FROM pg_stat_activity GROUP BY 1,2,3 ORDER BY 4 DESC;

-- Blocked queries (deadlocks/locks)
SELECT blocked.pid, blocked.query, blocking.pid AS blocking_pid, blocking.query AS blocking_query
FROM pg_stat_activity blocked
JOIN pg_locks bl ON bl.pid = blocked.pid
JOIN pg_locks bll ON bll.locktype = bl.locktype AND bll.relation = bl.relation AND bll.pid != bl.pid
JOIN pg_stat_activity blocking ON blocking.pid = bll.pid
WHERE NOT bl.granted;

-- Stuck jobs
SELECT id, job_type, status, claimed_by, created_at, updated_at
FROM ops.jobs WHERE status = 'in_progress' AND updated_at < NOW() - INTERVAL '10 minutes';
```

---

## 3. Remediation

### Env Hygiene

```powershell
# Verify env vars are correct
. ./scripts/load_env.ps1
python -c "from src.supabase_client import get_supabase_env; print(get_supabase_env())"
```

### Apply Missing Grants/RLS

```powershell
# Push migrations (includes security policies)
./scripts/db_push.ps1 -SupabaseEnv prod

# Reload PostgREST schema cache
python -m tools.pgrst_reload --env prod
```

### Rollback (if bad deploy)

```powershell
# Redeploy previous known-good SHA
railway deploy --service dragonfly-api --commit <GOOD_SHA>

# Or revert last migration
psql $SUPABASE_DB_URL -f supabase/migrations/<timestamp>_rollback.sql
```

### Release Stuck Jobs

```sql
UPDATE ops.jobs SET status = 'pending', claimed_by = NULL, updated_at = NOW()
WHERE status = 'in_progress' AND updated_at < NOW() - INTERVAL '15 minutes';
```

---

## 4. Verification

```powershell
# Prod gate (skip slow checks)
python -m tools.prod_gate --mode prod --skip pytest lint evaluator

# Health check
curl -s https://dragonfly-api.railway.app/health | jq .

# Golden path smoke (read-only)
python -m tools.smoke_plaintiffs --env prod --limit 5
```

---

## 5. Postmortem Checklist

| Item                                             | Owner | Done |
| ------------------------------------------------ | ----- | ---- |
| Root cause identified (logs, metrics, code diff) |       | ☐    |
| Timeline documented (first symptom → resolution) |       | ☐    |
| Missing test added (unit/integration)            |       | ☐    |
| Monitoring gap closed (alert added)              |       | ☐    |
| Runbook updated if new failure mode              |       | ☐    |
| `prod_gate` check added if detectable pre-deploy |       | ☐    |
| Security review if permission-related            |       | ☐    |

---

**Escalation:** If unresolved in 15 min, page on-call lead. If data corruption suspected, freeze all writes and notify stakeholders immediately.
