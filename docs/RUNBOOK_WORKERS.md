# Dragonfly Civil – Worker Entrypoints

**How to run workers locally and on Railway**

_Version 1.0 | January 2025_

---

## Overview

All Dragonfly workers use the `WorkerBootstrap` infrastructure from
[backend/workers/bootstrap.py](../backend/workers/bootstrap.py) which provides:

- **Graceful shutdown** – SIGTERM/SIGINT handling
- **Exponential backoff** – Shared `BackoffState` for transient failure recovery
- **InFailedSqlTransaction recovery** – Auto-rollback and reconnect
- **Heartbeat registration** – Status tracking via `ops.worker_heartbeats`
- **Crash loop detection** – Halts worker after 10 consecutive failures

---

## Worker Entrypoints

| Worker             | Module Path                                | Job Type(s)          |
| ------------------ | ------------------------------------------ | -------------------- |
| Simplicity Ingest  | `backend.workers.simplicity_ingest_worker` | `simplicity_ingest`  |
| Ingest Processor   | `backend.workers.ingest_processor`         | `intake`, `ingest`   |
| Enforcement Engine | `backend.workers.enforcement_engine`       | `enforcement_action` |

---

## Local Development

### Prerequisites

1. Activate virtual environment:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

2. Set environment to dev:

   ```powershell
   $env:SUPABASE_MODE = "dev"
   ```

3. Load environment variables:
   ```powershell
   . .\scripts\load_env.ps1
   ```

### Run Commands

**Simplicity Ingest Worker:**

```powershell
python -m backend.workers.simplicity_ingest_worker
```

**Ingest Processor:**

```powershell
python -m backend.workers.ingest_processor
```

**Enforcement Engine:**

```powershell
python -m backend.workers.enforcement_engine
```

### Single-Iteration Testing

For one-shot runs (useful for debugging):

```powershell
# Run watcher once without looping
.\scripts\run_watcher.ps1 -Once
```

---

## Railway Deployment

### Environment Variables

Set these in your Railway service:

| Variable                         | Value                    | Notes                       |
| -------------------------------- | ------------------------ | --------------------------- |
| `SUPABASE_MODE`                  | `prod`                   | Required for production DSN |
| `SUPABASE_DB_URL_PROD`           | `postgresql://...`       | Direct DB connection        |
| `SUPABASE_URL_PROD`              | `https://...supabase.co` | REST API endpoint           |
| `SUPABASE_SERVICE_ROLE_KEY_PROD` | `eyJ...`                 | Service role key            |

### Procfile Workers

Railway reads from `Procfile` or individual service definitions:

```
worker: python -m backend.workers.simplicity_ingest_worker
```

### Service-Specific Commands

| Service Name         | Start Command                                        |
| -------------------- | ---------------------------------------------------- |
| `simplicity-ingest`  | `python -m backend.workers.simplicity_ingest_worker` |
| `ingest-processor`   | `python -m backend.workers.ingest_processor`         |
| `enforcement-engine` | `python -m backend.workers.enforcement_engine`       |

---

## Monitoring

### Heartbeat Table

Workers register themselves to `ops.worker_heartbeats`:

```sql
SELECT worker_id, worker_type, status, last_heartbeat_at
FROM ops.worker_heartbeats
WHERE last_heartbeat_at > now() - interval '5 minutes'
ORDER BY last_heartbeat_at DESC;
```

### Status Values

| Status     | Meaning                         |
| ---------- | ------------------------------- |
| `starting` | Worker initializing             |
| `running`  | Normal operation                |
| `degraded` | Recovering from transient error |
| `stopped`  | Clean shutdown                  |
| `error`    | Crash loop or fatal error       |

---

## Error Recovery

### InFailedSqlTransaction

When a Postgres transaction enters failed state:

1. Worker catches `psycopg.errors.InFailedSqlTransaction`
2. Attempts `conn.rollback()`
3. If rollback fails → closes connection → reconnects
4. Backoff delay applied before retry

### Exponential Backoff

The shared `BackoffState` class ([backend/workers/backoff.py](../backend/workers/backoff.py)):

- Initial delay: 1 second
- Multiplier: 2x per failure
- Max delay: 60 seconds
- Jitter: ±10% to prevent thundering herd
- Crash loop threshold: 10 consecutive failures

### Crash Loop Handling

After 10 consecutive failures without success:

1. Worker logs `CRITICAL: Crash loop detected`
2. Heartbeat status set to `error`
3. Worker raises `RuntimeError` and exits
4. Railway/supervisor should restart the service

---

## VS Code Tasks

Use these tasks from the command palette (`Ctrl+Shift+P` → Tasks: Run Task):

| Task            | Description                                   |
| --------------- | --------------------------------------------- |
| `Workers: Run`  | Start all workers via scripts/run_workers.ps1 |
| `Watcher: Once` | Single watcher iteration for testing          |
| `Doctor All`    | Health check all worker dependencies          |

---

## Troubleshooting

### Worker Won't Start

1. Check `SUPABASE_MODE` is set correctly
2. Run doctor: `python -m tools.doctor --env dev`
3. Verify DB connectivity: `python -m tools.smoke_plaintiffs`

### Jobs Not Processing

1. Check for pending jobs:

   ```sql
   SELECT * FROM ops.jobs
   WHERE status = 'pending'
   ORDER BY created_at DESC
   LIMIT 10;
   ```

2. Check for stuck locks:

   ```sql
   SELECT * FROM ops.jobs
   WHERE status = 'processing'
   AND locked_at < now() - interval '10 minutes';
   ```

3. Verify worker heartbeat is recent (see Monitoring section)

### High Backoff Delays

If a worker is in constant backoff:

1. Check DB connectivity from the worker's network
2. Review `ops.worker_heartbeats` for `degraded` status
3. Check PostgreSQL logs for connection errors
