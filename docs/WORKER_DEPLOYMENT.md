# Dragonfly Worker Deployment Guide

> **Target Platform**: Railway (or any container-based PaaS)  
> **Strategy**: One Service Per Worker Type (Isolation)  
> **Last Updated**: January 2026

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Service Catalog](#service-catalog)
3. [Environment Variables](#environment-variables)
4. [Job Envelope Specification](#job-envelope-specification)
5. [Railway Configuration](#railway-configuration)
6. [Scaling Guidelines](#scaling-guidelines)
7. [Health Monitoring](#health-monitoring)
8. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           RAILWAY PROJECT                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────────┐   ┌─────────────────────┐   ┌──────────────────┐  │
│   │  dragonfly-api      │   │ dragonfly-worker-   │   │ dragonfly-       │  │
│   │  (FastAPI)          │   │ ingest              │   │ worker-score     │  │
│   │                     │   │                     │   │                  │  │
│   │  Port: $PORT        │   │  q_ingest_raw       │   │  q_score_*       │  │
│   └─────────┬───────────┘   └─────────┬───────────┘   └────────┬─────────┘  │
│             │                         │                        │            │
│             └─────────────┬───────────┴────────────────────────┘            │
│                           │                                                  │
│                           ▼                                                  │
│               ┌───────────────────────┐                                      │
│               │   Supabase Postgres   │                                      │
│               │   (pgmq queues)       │                                      │
│               └───────────────────────┘                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why "One Service Per Worker"?

| Benefit                     | Description                                                    |
| --------------------------- | -------------------------------------------------------------- |
| **Isolation**               | A crash in one worker doesn't affect others                    |
| **Independent Scaling**     | Scale ingest workers without scaling scoring workers           |
| **Resource Tuning**         | Assign more RAM to AI workers, less to simple queue processors |
| **Deployment Independence** | Deploy/rollback workers independently                          |
| **Clear Metrics**           | Railway shows per-service CPU/memory/logs                      |

---

## Service Catalog

### Production Services

| Service Name                   | Start Command                                          | Queue(s) Consumed        | Purpose                   |
| ------------------------------ | ------------------------------------------------------ | ------------------------ | ------------------------- |
| `dragonfly-api`                | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` | N/A (REST API)           | FastAPI backend           |
| `dragonfly-worker-ingest`      | `python -m backend.workers.ingest_processor`           | `q_ingest_raw`           | CSV import processing     |
| `dragonfly-worker-enforcement` | `python -m backend.workers.enforcement_engine`         | `q_enforcement_*`        | AI enforcement pipelines  |
| `dragonfly-worker-simplicity`  | `python -m backend.workers.simplicity_ingest_worker`   | `q_simplicity_*`         | Simplicity vendor imports |
| `dragonfly-worker-score`       | `python -m backend.workers.collectability`             | `q_score_collectability` | Collectability scoring    |
| `dragonfly-worker-comms`       | `python -m backend.workers.outbox_processor`           | `q_comms_outbound`       | Outbound communications   |

### Naming Convention

```
dragonfly-worker-{function}

Examples:
  dragonfly-worker-ingest      # Data ingestion
  dragonfly-worker-score       # Scoring/classification
  dragonfly-worker-enforce     # Enforcement actions
  dragonfly-worker-comms       # Communications/notifications
```

---

## Environment Variables

### Required (All Services)

| Variable                    | Description                  | Example                                                         |
| --------------------------- | ---------------------------- | --------------------------------------------------------------- |
| `SUPABASE_URL`              | Supabase project URL         | `https://abc123.supabase.co`                                    |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (not anon!) | `eyJhbG...` (100+ chars)                                        |
| `SUPABASE_DB_URL`           | Postgres connection string   | `postgresql://postgres:***@db.abc123.supabase.co:5432/postgres` |
| `SUPABASE_MODE`             | Environment identifier       | `prod` or `dev`                                                 |
| `ENVIRONMENT`               | Runtime environment          | `production`                                                    |

### Worker-Specific

| Variable              | Required By                    | Description                              |
| --------------------- | ------------------------------ | ---------------------------------------- |
| `OPENAI_API_KEY`      | `dragonfly-worker-enforcement` | OpenAI API for AI agents                 |
| `DISCORD_WEBHOOK_URL` | All (optional)                 | Discord alerting webhook                 |
| `WORKER_VERSION`      | All (optional)                 | Version string for heartbeats            |
| `HEARTBEAT_INTERVAL`  | All (optional)                 | Seconds between heartbeats (default: 30) |

### API-Specific

| Variable                 | Required By     | Description              |
| ------------------------ | --------------- | ------------------------ |
| `DRAGONFLY_API_KEY`      | `dragonfly-api` | API authentication key   |
| `PORT`                   | `dragonfly-api` | Auto-injected by Railway |
| `DRAGONFLY_CORS_ORIGINS` | `dragonfly-api` | Allowed CORS origins     |

---

## Job Envelope Specification

All messages on pgmq queues **MUST** conform to the `JobEnvelope` schema.  
Invalid envelopes are sent directly to the Dead Letter Queue (no retry).

### Schema

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "trace_id": "660e8400-e29b-41d4-a716-446655440001",
  "org_id": "770e8400-e29b-41d4-a716-446655440002",
  "idempotency_key": "plaintiff:intake:12345",
  "entity_type": "plaintiff",
  "entity_id": "12345",
  "attempt": 1,
  "created_at": "2026-01-06T12:00:00Z",
  "payload": {
    "action": "score_collectability",
    "priority": "high"
  }
}
```

### Field Reference

| Field             | Type     | Required | Description                                         |
| ----------------- | -------- | -------- | --------------------------------------------------- |
| `job_id`          | UUID     | Auto     | Unique job identifier                               |
| `trace_id`        | UUID     | Auto     | Distributed tracing ID                              |
| `org_id`          | UUID     | **Yes**  | Tenant organization ID                              |
| `idempotency_key` | string   | **Yes**  | Unique key for exactly-once (max 512 chars)         |
| `entity_type`     | string   | **Yes**  | Entity type: `plaintiff`, `judgment`, `enforcement` |
| `entity_id`       | string   | **Yes**  | Entity identifier                                   |
| `attempt`         | int      | Auto     | Retry counter (starts at 1)                         |
| `created_at`      | datetime | Auto     | Job creation timestamp                              |
| `payload`         | object   | **Yes**  | Job-specific data                                   |

### Example: Ingest Job

```json
{
  "job_id": "a1b2c3d4-...",
  "trace_id": "e5f6g7h8-...",
  "org_id": "org-dragonfly-prod",
  "idempotency_key": "ingest:batch:2026-01-06-001",
  "entity_type": "batch",
  "entity_id": "batch-2026-01-06-001",
  "attempt": 1,
  "created_at": "2026-01-06T10:00:00Z",
  "payload": {
    "file_path": "uploads/simplicity_2026-01-06.csv",
    "source": "simplicity",
    "row_count": 150
  }
}
```

### Example: Scoring Job

```json
{
  "job_id": "b2c3d4e5-...",
  "trace_id": "e5f6g7h8-...",
  "org_id": "org-dragonfly-prod",
  "idempotency_key": "score:plaintiff:12345",
  "entity_type": "plaintiff",
  "entity_id": "12345",
  "attempt": 1,
  "created_at": "2026-01-06T10:05:00Z",
  "payload": {
    "action": "compute_collectability",
    "judgment_ids": ["j-001", "j-002", "j-003"]
  }
}
```

---

## Railway Configuration

### Step 1: Create Services

In Railway dashboard, create each worker as a separate service:

```bash
# Service 1: API
Name: dragonfly-api
Start Command: uvicorn backend.main:app --host 0.0.0.0 --port $PORT

# Service 2: Ingest Worker
Name: dragonfly-worker-ingest
Start Command: python -m backend.workers.ingest_processor

# Service 3: Enforcement Worker
Name: dragonfly-worker-enforcement
Start Command: python -m backend.workers.enforcement_engine

# Service 4: Simplicity Worker
Name: dragonfly-worker-simplicity
Start Command: python -m backend.workers.simplicity_ingest_worker
```

### Step 2: Environment Variables

Use Railway's shared variable groups:

```bash
# Group: dragonfly-shared (apply to all services)
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
SUPABASE_DB_URL=postgresql://postgres:***@...
SUPABASE_MODE=prod
ENVIRONMENT=production
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Group: dragonfly-api (API only)
DRAGONFLY_API_KEY=sk-dragonfly-...
DRAGONFLY_CORS_ORIGINS=https://app.dragonfly.law

# Group: dragonfly-ai (AI workers only)
OPENAI_API_KEY=sk-...
```

### Step 3: Resource Allocation

| Service                        | Recommended Memory | Replicas |
| ------------------------------ | ------------------ | -------- |
| `dragonfly-api`                | 512 MB             | 2+       |
| `dragonfly-worker-ingest`      | 1 GB (CSV parsing) | 1-2      |
| `dragonfly-worker-enforcement` | 2 GB (AI models)   | 1        |
| `dragonfly-worker-simplicity`  | 512 MB             | 1        |
| `dragonfly-worker-score`       | 256 MB             | 1        |

---

## Scaling Guidelines

### When to Scale

| Signal                             | Action                                |
| ---------------------------------- | ------------------------------------- |
| Queue depth > 1000 for > 5 minutes | Add worker replica                    |
| Oldest message age > 30 minutes    | Check worker health, scale if healthy |
| Worker CPU > 80% sustained         | Scale horizontally                    |
| Worker memory > 85%                | Increase memory or optimize           |

### Horizontal Scaling

Workers are designed for horizontal scaling:

```
# Add 2 more ingest workers
dragonfly-worker-ingest-1  # Replica 1
dragonfly-worker-ingest-2  # Replica 2
dragonfly-worker-ingest-3  # Replica 3
```

Each worker uses `FOR UPDATE SKIP LOCKED` for safe concurrent dequeue.

### Autoscaling (Railway Pro)

```yaml
# Example autoscale config (if supported)
services:
  dragonfly-worker-ingest:
    minReplicas: 1
    maxReplicas: 5
    targetCPU: 70
```

---

## Health Monitoring

### Heartbeat Table

Workers report to `workers.heartbeats` every 30 seconds:

```sql
SELECT
    queue_name,
    status,
    last_heartbeat_at,
    jobs_processed,
    jobs_failed
FROM workers.heartbeats
WHERE last_heartbeat_at > now() - INTERVAL '5 minutes';
```

### Queue Metrics

Check queue depth and worker status:

```bash
# Interactive dashboard
python -m tools.queue_inspect --env prod

# JSON for monitoring
python -m tools.queue_inspect --env prod --json
```

### Worker Monitor (Alerting)

Detect stale workers and alert Discord:

```bash
# One-time check
python -m tools.monitor_workers --env prod --alert

# Continuous monitoring (cron job or separate service)
python -m tools.monitor_workers --env prod --watch --alert --interval 60
```

### Health Endpoints

| Endpoint                  | Description             |
| ------------------------- | ----------------------- |
| `GET /health`             | API liveness check      |
| `GET /health/db`          | Database connectivity   |
| `workers.v_worker_health` | SQL view of all workers |
| `workers.v_queue_metrics` | SQL view of queue stats |

---

## Troubleshooting

### Worker Not Processing Jobs

1. **Check heartbeats**:

   ```bash
   python -m tools.monitor_workers --env prod
   ```

2. **Check queue depth**:

   ```bash
   python -m tools.queue_inspect --env prod
   ```

3. **Check Railway logs**:

   - Go to service → Logs
   - Look for connection errors or exceptions

4. **Verify environment variables**:
   - Missing `SUPABASE_DB_URL` = no database connection
   - Wrong `SUPABASE_MODE` = connecting to wrong project

### Invalid Envelope Errors

Jobs sent to DLQ with "Invalid Envelope" reason:

1. **Inspect DLQ**:

   ```sql
   SELECT * FROM pgmq.q_dead_letter
   ORDER BY enqueued_at DESC
   LIMIT 10;
   ```

2. **Check required fields**:

   - `org_id` (UUID, required)
   - `idempotency_key` (string, required)
   - `entity_type` (string, required)
   - `entity_id` (string, required)

3. **Validate envelope schema**:
   ```python
   from backend.workers.envelope import JobEnvelope
   JobEnvelope.parse(your_payload)  # Raises InvalidEnvelopeError if bad
   ```

### Worker Crashes on Startup

1. **Check import errors**:

   ```bash
   python -c "from backend.workers.ingest_processor import *"
   ```

2. **Check database connectivity**:

   ```bash
   python -c "from src.supabase_client import get_supabase_db_url; print(get_supabase_db_url())"
   ```

3. **Check Railway build logs**:
   - Missing dependencies = add to `requirements.txt`
   - Wrong Python version = check `runtime.txt`

### Discord Alerts Not Sending

1. **Verify webhook URL**:

   ```bash
   python -m tools.test_discord
   ```

2. **Check environment variable**:

   - `DISCORD_WEBHOOK_URL` must be set

3. **Check network access**:
   - Railway → Settings → Networking
   - Ensure outbound HTTPS is allowed

---

## Quick Reference

### Start Commands

```bash
# API
uvicorn backend.main:app --host 0.0.0.0 --port $PORT

# Workers
python -m backend.workers.ingest_processor
python -m backend.workers.enforcement_engine
python -m backend.workers.simplicity_ingest_worker
python -m backend.workers.collectability
python -m backend.workers.outbox_processor
```

### Monitoring Commands

```bash
# Queue dashboard
python -m tools.queue_inspect --env prod

# Worker health
python -m tools.monitor_workers --env prod

# Send test alert
python -m tools.test_discord
```

### Database Views

```sql
-- Worker health
SELECT * FROM workers.v_worker_health;

-- Queue metrics
SELECT * FROM workers.v_queue_metrics;

-- Find stale workers
SELECT * FROM workers.find_stale_workers(5);
```

---

## Related Documentation

- [WORKERS_RUNBOOK.md](WORKERS_RUNBOOK.md) - Operational procedures
- [envelope.py](../backend/workers/envelope.py) - JobEnvelope source
- [base.py](../backend/workers/base.py) - BaseWorker implementation
- [Procfile](../Procfile) - Process definitions
