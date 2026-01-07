# Railway Worker Configuration Guide

> **Classification:** INTERNAL – DevOps / Platform Engineering  
> **Last Updated:** 2026-01-07  
> **Owner:** DevOps Lead

---

## 🎯 Purpose

This guide defines the **configuration contract** for Dragonfly worker services deployed on Railway. Following these guidelines prevents false-positive restarts, OOM kills, and healthcheck loops.

---

## 📋 Quick Reference

| Setting           | Value                              | Why                                        |
| ----------------- | ---------------------------------- | ------------------------------------------ |
| **Start Command** | `python -m backend.workers.<name>` | Direct execution, no WSGI overhead         |
| **Concurrency**   | 1 process                          | Predictable memory, exactly-once semantics |
| **RAM**           | 512 MB (start)                     | Scale up in 256 MB increments if needed    |
| **vCPU**          | 0.5                                | Workers are I/O bound, not CPU bound       |
| **Healthcheck**   | **DISABLED**                       | Workers don't expose HTTP ports            |

---

## 1️⃣ Start Command

### ✅ Correct Configuration

```bash
python -m backend.workers.collectability
python -m backend.workers.escalation
python -m backend.workers.outbox_processor
```

### ❌ Do NOT Use

```bash
# WRONG - Gunicorn is for HTTP services, not queue workers
gunicorn backend.workers.collectability:app

# WRONG - Uvicorn is for ASGI HTTP services
uvicorn backend.workers.collectability:app

# WRONG - Multiple processes break exactly-once semantics
python -m backend.workers.collectability --workers 4
```

### Why Direct Python Execution?

1. **No HTTP Layer:** Workers consume from pgmq queues, not HTTP requests
2. **Predictable Memory:** Single process = predictable RAM usage
3. **Exactly-Once Semantics:** Multiple processes can cause race conditions with idempotency
4. **Clean Signals:** Python receives SIGTERM directly for graceful shutdown

---

## 2️⃣ Healthchecks

### ⚠️ CRITICAL: Disable Healthchecks for Worker Services

Railway's default behavior is to enable TCP or HTTP healthchecks. **This will cause a restart loop for workers.**

### Railway Dashboard Configuration

1. Go to **Project → Worker Service → Settings**
2. Navigate to **Deploy → Health Checks**
3. Set **Health Check Type** to **None** (or disable entirely)

### Why Disable?

| Healthcheck Type | What Happens                          | Result                          |
| ---------------- | ------------------------------------- | ------------------------------- |
| **TCP**          | Railway tries to connect to a port    | ❌ Connection refused → Restart |
| **HTTP**         | Railway sends GET to `/health`        | ❌ No response → Restart        |
| **None**         | Railway trusts the process is running | ✅ Works correctly              |

### Alternative Health Monitoring

Instead of Railway healthchecks, we use:

1. **Structured Boot Logs:** Workers emit `WORKER_BOOT` JSON on startup
2. **Heartbeat Table:** Workers write to `workers.heartbeats` every 30 seconds
3. **Worker Inspector:** Use `python -m tools.worker_inspector` to check health

#### Verifying Worker Health via Logs

```bash
# In Railway logs, look for:
{"event": "WORKER_BOOT", "data": {"worker_name": "q_collectability", "db_status": "ok", ...}}

# On redeploy/scale-down:
{"event": "WORKER_SHUTDOWN", "data": {"reason": "SIGTERM (Deployment/Scale-down)", ...}}

# On crash:
{"event": "WORKER_CRASH", "data": {"error": "...", "error_type": "MemoryError", ...}}
```

#### Verifying Worker Health via Database

```sql
-- Check active workers
SELECT worker_id, queue_name, status, last_heartbeat_at
FROM workers.heartbeats
WHERE last_heartbeat_at > NOW() - INTERVAL '2 minutes';
```

---

## 3️⃣ Resource Limits

### Starting Configuration

| Resource | Initial Value | Notes                               |
| -------- | ------------- | ----------------------------------- |
| **RAM**  | 512 MB        | Suitable for most queue processing  |
| **vCPU** | 0.5           | Workers are I/O bound (DB, network) |

### Scaling RAM

If you see `WORKER_CRASH` logs with exit code 137 (OOM Killed):

```json
{"event": "WORKER_CRASH", "data": {"error": "...", "error_type": "MemoryError", ...}}
```

Or in Railway metrics, you see RAM hitting 100%:

1. **Increase RAM by 256 MB increments**
2. Typical progression: `512 MB → 768 MB → 1024 MB`
3. If worker needs > 1 GB, investigate for memory leaks

### Exit Codes Reference

| Exit Code | Meaning                  | Action                               |
| --------- | ------------------------ | ------------------------------------ |
| **0**     | Clean shutdown (SIGTERM) | Normal - deployment/scale-down       |
| **1**     | Application error        | Check `WORKER_CRASH` log for details |
| **137**   | OOM Killed (128 + 9)     | Increase RAM by 256 MB               |
| **143**   | SIGTERM (128 + 15)       | Normal - graceful shutdown           |

---

## 4️⃣ Environment Variables

### Required

```bash
SUPABASE_DB_URL=postgresql://...     # Database connection string
SUPABASE_MODE=prod                   # Environment (dev/prod)
```

### Optional (Auto-detected)

```bash
RAILWAY_GIT_COMMIT_SHA=abc123...     # Git SHA (auto-set by Railway)
WORKER_VERSION=1.0.0                 # Worker version for heartbeats
```

---

## 5️⃣ Deployment Checklist

Before deploying a new worker service:

- [ ] Start command uses `python -m backend.workers.<name>`
- [ ] Healthchecks are **disabled**
- [ ] RAM set to 512 MB (or higher if previously OOM'd)
- [ ] vCPU set to 0.5
- [ ] `SUPABASE_DB_URL` and `SUPABASE_MODE` environment variables set
- [ ] Worker inherits from `BaseWorker` (for structured logging)

### Post-Deployment Verification

1. **Check Railway Logs** for `WORKER_BOOT` event:

   ```json
   {"event": "WORKER_BOOT", "data": {"db_status": "ok", ...}}
   ```

2. **Check Heartbeats** (within 60 seconds):

   ```sql
   SELECT * FROM workers.heartbeats
   WHERE queue_name = 'q_<your_worker>'
   ORDER BY last_heartbeat_at DESC LIMIT 1;
   ```

3. **Monitor for Crashes** over next 5 minutes:
   - No `WORKER_CRASH` events in logs
   - No unexpected restarts in Railway dashboard

---

## 6️⃣ Troubleshooting

### Worker Keeps Restarting

| Symptom                       | Likely Cause                    | Fix                                |
| ----------------------------- | ------------------------------- | ---------------------------------- |
| Restarts every 30s exactly    | Healthcheck enabled             | Disable healthchecks               |
| Restarts with exit code 137   | OOM                             | Increase RAM by 256 MB             |
| Restarts immediately on start | Missing env var or import error | Check `WORKER_BOOT` log for errors |
| No logs at all                | Crash before logging starts     | Check Railway build logs           |

### Worker Not Processing Jobs

1. Verify queue has messages:

   ```sql
   SELECT COUNT(*) FROM pgmq.q_<queue_name>;
   ```

2. Check worker heartbeat is recent:

   ```sql
   SELECT * FROM workers.heartbeats WHERE queue_name = 'q_<name>';
   ```

3. Check for idempotency blocks:
   ```sql
   SELECT * FROM workers.processed_jobs
   WHERE status = 'processing'
   AND updated_at < NOW() - INTERVAL '5 minutes';
   ```

---

## 📚 Related Documentation

- [Disaster Recovery Runbook](RUNBOOK_DISASTER_RECOVERY.md) – Database restore procedures
- [Worker Inspector Tool](../tools/worker_inspector.py) – Health monitoring CLI
- [BaseWorker Implementation](../backend/workers/base.py) – Structured logging source

---

## 📝 Revision History

| Date       | Author      | Change           |
| ---------- | ----------- | ---------------- |
| 2026-01-07 | DevOps Lead | Initial creation |
