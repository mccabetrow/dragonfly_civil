# Dragonfly Workers Runbook

> **Version:** 1.0  
> **Last Updated:** 2026-01-01  
> **Maintainers:** Platform Engineering Team

This runbook documents the Dragonfly Worker System—a distributed, observable, and resilient job processing infrastructure built on **pgmq** (Postgres Message Queue).

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Queue Topology Map](#queue-topology-map)
3. [Message Lifecycle](#message-lifecycle)
4. [Worker Implementation Guide](#worker-implementation-guide)
5. [Poison Message Handling](#poison-message-handling)
6. [Operational Tools](#operational-tools)
7. [Scaling Workers](#scaling-workers)
8. [Idempotency Rules](#idempotency-rules)
9. [Monitoring & Alerts](#monitoring--alerts)
10. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DRAGONFLY WORKER SYSTEM                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐ │
│   │   Ingest    │    │   Enrich    │    │   Scoring   │    │   Comms     │ │
│   │   Worker    │    │   Worker    │    │   Worker    │    │   Worker    │ │
│   └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘ │
│          │                  │                  │                  │         │
│          ▼                  ▼                  ▼                  ▼         │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                         pgmq (Postgres)                             │   │
│   │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────┐  │   │
│   │  │q_ingest_raw  │ │q_enrich_skip │ │q_score_coll  │ │q_comms_out │  │   │
│   │  └──────────────┘ └──────────────┘ └──────────────┘ └────────────┘  │   │
│   │                                                                     │   │
│   │  ┌──────────────┐ ┌──────────────┐                                  │   │
│   │  │q_monitor_re  │ │q_dead_letter │ ◄── Poison Messages              │   │
│   │  └──────────────┘ └──────────────┘                                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                    workers.processed_jobs                           │   │
│   │                    (Idempotency Registry)                           │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Core Components:**

| Component            | Technology                | Purpose                   |
| -------------------- | ------------------------- | ------------------------- |
| Message Broker       | pgmq (Postgres extension) | Transactional job queuing |
| Idempotency Registry | `workers.processed_jobs`  | Exactly-once processing   |
| Dead Letter Tracking | `workers.dead_letter_log` | Failure forensics         |
| Base Worker          | `backend/workers/base.py` | Standardized lifecycle    |

---

## Queue Topology Map

The system uses **6 distinct queues** for workload isolation:

| Queue                    | Purpose                                        | Producers                                   | Consumers                         |
| ------------------------ | ---------------------------------------------- | ------------------------------------------- | --------------------------------- |
| `q_ingest_raw`           | New CSV/API payloads arriving for processing   | ETL importers, API endpoints, file watchers | `IngestWorker`                    |
| `q_enrich_skiptrace`     | Data enhancement via skip-trace services       | Ingest worker (post-validation)             | `EnrichWorker`                    |
| `q_score_collectability` | Tier A/B/C calculation for prioritization      | Enrich worker, monitoring recheck           | `ScoringWorker`                   |
| `q_monitoring_recheck`   | Periodic status checks on active cases         | Scheduler (cron), external triggers         | `MonitorWorker`                   |
| `q_comms_outbound`       | Outbound communications (emails, letters, SMS) | State transitions, escalation engine        | `CommsWorker`                     |
| `q_dead_letter`          | Failed jobs that exceeded retry limits         | All workers (after max retries)             | Manual replay via `replay_dlq.py` |

### Queue Flow Diagram

```
CSV Upload ──► q_ingest_raw ──► q_enrich_skiptrace ──► q_score_collectability
                                                              │
                                                              ▼
                                                    Plaintiff Prioritized
                                                              │
              ┌───────────────────────────────────────────────┘
              │
              ▼
     q_comms_outbound ◄─── Escalation Engine
              │
              ▼
     Letter/Email Sent

     q_monitoring_recheck ◄─── Scheduler (hourly/daily)
              │
              ▼
     Re-score if status changed
```

---

## Message Lifecycle

Every message follows the **Poll → Lease → Idempotency Check → Process → Ack/Archive** flow:

```
                              ┌─────────────────────────────────────┐
                              │           MESSAGE LIFECYCLE         │
                              └─────────────────────────────────────┘

  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
  │  1. POLL │───►│ 2. LEASE │───►│ 3. CHECK │───►│4. PROCESS│───►│  5. ACK  │
  └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
       │               │               │               │               │
       ▼               ▼               ▼               ▼               ▼
  pgmq.read()     Visibility      Idempotency      Business       pgmq.archive()
  with vt=30s     timeout set     key lookup       logic runs     or move to DLQ

                                       │
                                       ▼
                              ┌─────────────────┐
                              │ Already seen?   │
                              │ Skip + Archive  │
                              └─────────────────┘
```

### Detailed Steps

| Step               | Operation                           | Database Action                                        | Failure Behavior                 |
| ------------------ | ----------------------------------- | ------------------------------------------------------ | -------------------------------- |
| **1. Poll**        | Worker reads batch from queue       | `pgmq.read(queue, vt, limit)`                          | Retry with backoff               |
| **2. Lease**       | Message becomes invisible to others | `vt` column set to `now() + visibility_timeout`        | —                                |
| **3. Idempotency** | Check if already processed          | `SELECT FROM workers.processed_jobs`                   | If found: skip & archive         |
| **4. Claim**       | Register processing intent          | `INSERT INTO workers.processed_jobs`                   | Conflict = another worker has it |
| **5. Process**     | Execute business logic              | Your `process(payload)` method                         | Exception triggers retry         |
| **6. Complete**    | Mark success                        | `UPDATE workers.processed_jobs SET status='completed'` | —                                |
| **7. Archive**     | Remove from queue                   | `pgmq.archive(queue, msg_id)`                          | —                                |
| **6b. Fail**       | Mark failure                        | `UPDATE workers.processed_jobs SET status='failed'`    | If retries exhausted → DLQ       |

### Visibility Timeout

When a worker reads a message, it becomes **invisible** for `visibility_timeout` seconds (default: 30s). If the worker crashes:

- Message becomes visible again after timeout
- Another worker picks it up
- Idempotency check prevents double-processing if first worker actually completed

---

## Worker Implementation Guide

### Creating a New Worker

All workers inherit from `BaseWorker`:

```python
# backend/workers/my_new_worker.py
from backend.workers.base import BaseWorker

class MyNewWorker(BaseWorker):
    """Process items from q_ingest_raw."""

    def __init__(self):
        super().__init__(
            queue_name="q_ingest_raw",
            batch_size=10,           # Messages per poll
            visibility_timeout=30,   # Seconds before re-delivery
            max_retries=3,           # Before moving to DLQ
        )

    def process(self, payload: dict) -> dict | None:
        """
        Business logic goes here.

        Args:
            payload: The message body (already parsed JSON)

        Returns:
            Optional result dict (stored in processed_jobs.result)

        Raises:
            Exception: Will be caught, logged, and retried
        """
        plaintiff_id = payload["plaintiff_id"]

        # Do the work...
        result = enrich_plaintiff(plaintiff_id)

        # Optionally chain to next queue
        self.send_to_queue("q_enrich_skiptrace", {
            "plaintiff_id": plaintiff_id,
            "source_record_id": payload["source_record_id"],
        })

        return {"enriched": True, "fields_added": 5}

    def get_idempotency_key(self, payload: dict) -> str:
        """
        Override for custom idempotency logic.
        Default: hash of entire payload.
        """
        return f"ingest:{payload['source_record_id']}"


if __name__ == "__main__":
    worker = MyNewWorker()
    worker.run()
```

### Running the Worker

```bash
# Local development
python -m backend.workers.my_new_worker

# Railway deployment
railway run python -m backend.workers.my_new_worker
```

---

## Poison Message Handling

A **poison message** is a job that consistently crashes workers (e.g., malformed data, missing required fields).

### Detection

The system detects poison messages when:

- `read_ct` (read count) exceeds `max_retries`
- Same idempotency key has `attempts >= max_retries` in `processed_jobs`

### Automatic DLQ Routing

When `max_retries` is exceeded, `BaseWorker` automatically:

1. Wraps original payload with error metadata
2. Sends to `q_dead_letter`
3. Logs to `workers.dead_letter_log`
4. Archives from source queue

### DLQ Message Structure

```json
{
  "original_queue": "q_ingest_raw",
  "original_job_id": 12345,
  "original_payload": { ... },
  "error_message": "KeyError: 'plaintiff_id'",
  "attempt_count": 3,
  "moved_to_dlq_at": "2026-01-01T12:00:00Z"
}
```

### Manual Recovery

Use `replay_dlq.py` to resurrect failed jobs:

```bash
# Step 1: Inspect the DLQ
python -m tools.replay_dlq --dry-run

# Step 2: Filter by queue if needed
python -m tools.replay_dlq --queue q_ingest_raw --dry-run

# Step 3: Fix the root cause (code or data)

# Step 4: Replay the messages
python -m tools.replay_dlq --queue q_ingest_raw --limit 10 --yes

# For production, always dry-run first!
python -m tools.replay_dlq --env prod --dry-run
```

### Workflow: Recovering from a Bad Deployment

```
1. Worker crashes repeatedly on message #12345
2. Message moves to q_dead_letter after 3 retries
3. SRE investigates: python -m tools.replay_dlq --dry-run
4. Identifies bug: missing null check for "middle_name"
5. Developer fixes code, deploys new version
6. SRE replays: python -m tools.replay_dlq --queue q_ingest_raw --yes
7. Message reprocesses successfully
```

---

## Operational Tools

### Queue Inspector (`tools/queue_inspect.py`)

Real-time dashboard for queue health:

```bash
# Default dashboard
python -m tools.queue_inspect

# Target specific environment
python -m tools.queue_inspect --env prod

# JSON output for alerting/Datadog
python -m tools.queue_inspect --json

# Continuous monitoring (refreshes every 5s)
python -m tools.queue_inspect --watch
```

**Sample Output:**

```
================================================================================
  DRAGONFLY QUEUE DASHBOARD  |  Environment: DEV
  Timestamp: 2026-01-01T14:30:00+00:00
================================================================================

Queue Name                   Total      Oldest       Processing   Readable
--------------------------------------------------------------------------------
q_ingest_raw                 42         3m           2            40
q_enrich_skiptrace           15         1m           1            14
q_score_collectability       8          30s          0            8
q_monitoring_recheck         0          -            0            0
q_comms_outbound             3          5m           1            2
⚠️  q_dead_letter            12         2h           0            12
--------------------------------------------------------------------------------

  Total Messages Across All Queues: 80
  Total Currently Processing:       4

  ⚠️  WARNING: Dead Letter Queue has 12 messages!
     Run: python -m tools.replay_dlq --dry-run to inspect
```

### DLQ Replayer (`tools/replay_dlq.py`)

Resurrect failed jobs:

```bash
# Preview without changes
python -m tools.replay_dlq --dry-run

# Filter by original queue
python -m tools.replay_dlq --queue q_ingest_raw

# Limit batch size
python -m tools.replay_dlq --limit 10

# Skip confirmation
python -m tools.replay_dlq --yes

# Production (always dry-run first!)
python -m tools.replay_dlq --env prod --dry-run
```

---

## Scaling Workers

### Horizontal Scaling

Each queue can have **multiple workers** consuming in parallel. pgmq guarantees:

- Each message is delivered to exactly one worker (via visibility timeout)
- No duplicate processing (via idempotency registry)

### Railway Deployment

```bash
# Scale ingest workers to 3 instances
railway up --service worker-ingest --replicas 3

# Scale scoring workers based on load
railway up --service worker-scoring --replicas 2
```

### Service Configuration (`railway.json`)

```json
{
  "services": {
    "worker-ingest": {
      "command": "python -m backend.workers.ingest_worker",
      "replicas": 2
    },
    "worker-enrich": {
      "command": "python -m backend.workers.enrich_worker",
      "replicas": 1
    },
    "worker-scoring": {
      "command": "python -m backend.workers.scoring_worker",
      "replicas": 1
    }
  }
}
```

### Autoscaling Guidelines

| Queue Depth | Action                               |
| ----------- | ------------------------------------ |
| < 100       | 1 worker                             |
| 100-1000    | 2-3 workers                          |
| 1000+       | 4+ workers, investigate backpressure |
| DLQ > 10    | **Alert!** Investigate failures      |

### Local Development (Multiple Workers)

```bash
# Terminal 1
python -m backend.workers.ingest_worker

# Terminal 2 (same worker, different instance)
python -m backend.workers.ingest_worker
```

Both will safely consume from the same queue without conflicts.

---

## Idempotency Rules

**Golden Rule:** Always include a stable identifier in your payload.

### Required Payload Fields

```python
{
    "source_record_id": "simplicity_2026_001234",  # REQUIRED
    "action": "ingest_plaintiff",                   # Recommended
    "plaintiff_id": "uuid-...",                     # If known
    "batch_id": "import_2026-01-01_001",           # For tracing
}
```

### Idempotency Key Derivation

Default: SHA-256 hash of entire payload.

Custom (recommended):

```python
def get_idempotency_key(self, payload: dict) -> str:
    return f"{self.queue_name}:{payload['source_record_id']}:{payload['action']}"
```

### Why This Matters

```
Scenario: Worker crashes after DB write but before pgmq.archive()

Without idempotency:
  - Message becomes visible again
  - Another worker picks it up
  - DUPLICATE DATA INSERTED ❌

With idempotency:
  - Message becomes visible again
  - Another worker picks it up
  - Idempotency check: "Already processed!"
  - Message archived, no duplicate ✅
```

### Best Practices

1. **Never use timestamps** as idempotency keys (not stable)
2. **Include action type** in the key (same record, different actions = different keys)
3. **Use source system IDs** when available (`simplicity_id`, `jbi_case_number`)
4. **Compound keys** for complex workflows: `ingest:{source_id}:{action}`

---

## Monitoring & Alerts

### Key Metrics

| Metric                 | Source                              | Alert Threshold      |
| ---------------------- | ----------------------------------- | -------------------- |
| Queue Depth            | `pgmq.metrics()`                    | > 1000 for 5 min     |
| DLQ Count              | `pgmq.metrics('q_dead_letter')`     | > 10                 |
| Oldest Message Age     | Queue inspect                       | > 1 hour             |
| Processing (Invisible) | Queue inspect                       | > 50% of total       |
| Worker Heartbeat       | `workers.processed_jobs.updated_at` | No updates for 5 min |

### Discord/Slack Alerts

```python
# In your monitoring job
metrics = fetch_queue_metrics(conn, "q_dead_letter")
if metrics.total_messages >= 10:
    send_alert(
        channel="#dragonfly-alerts",
        message=f"🚨 DLQ has {metrics.total_messages} messages! Run replay_dlq.py"
    )
```

### Grafana Dashboard Queries

```sql
-- Messages per queue (last 5 min)
SELECT queue_name, total_messages
FROM pgmq.metrics_all();

-- Failed jobs by hour
SELECT
  date_trunc('hour', moved_to_dlq_at) as hour,
  original_queue,
  COUNT(*) as failures
FROM workers.dead_letter_log
WHERE moved_to_dlq_at > NOW() - INTERVAL '24 hours'
GROUP BY 1, 2
ORDER BY 1 DESC;
```

---

## Troubleshooting

### Problem: Worker Not Processing Messages

**Symptoms:** Queue depth increasing, no worker activity.

**Checks:**

```bash
# 1. Is worker running?
railway logs --service worker-ingest

# 2. Can worker connect to DB?
python -m tools.doctor --env prod

# 3. Are messages invisible (being processed)?
python -m tools.queue_inspect
```

**Causes:**

- Worker crashed silently (check logs)
- Database connection pool exhausted
- Visibility timeout too short (messages timing out)

---

### Problem: Messages Stuck in "Processing"

**Symptoms:** High "Processing" count, low "Readable" count.

**Checks:**

```sql
-- Find old invisible messages
SELECT msg_id, enqueued_at, vt, read_ct
FROM pgmq.q_ingest_raw
WHERE vt > NOW()
ORDER BY vt DESC
LIMIT 20;
```

**Causes:**

- Worker crashed without archiving
- Very slow processing (increase `visibility_timeout`)
- Deadlock in business logic

**Fix:**

```sql
-- Force messages visible (careful in production!)
UPDATE pgmq.q_ingest_raw
SET vt = NOW() - INTERVAL '1 second'
WHERE vt > NOW() + INTERVAL '10 minutes';
```

---

### Problem: Duplicate Processing

**Symptoms:** Same record processed twice, duplicate data.

**Checks:**

```sql
-- Check for duplicate idempotency keys
SELECT idempotency_key, COUNT(*) as cnt
FROM workers.processed_jobs
GROUP BY idempotency_key
HAVING COUNT(*) > 1;
```

**Causes:**

- Idempotency key not unique enough
- Worker not using `BaseWorker`
- Race condition in custom implementation

**Fix:**

- Ensure `get_idempotency_key()` returns unique, stable values
- Migrate to `BaseWorker` pattern

---

### Problem: DLQ Growing Rapidly

**Symptoms:** `q_dead_letter` count spiking.

**Checks:**

```bash
# Inspect failure reasons
python -m tools.replay_dlq --dry-run
```

```sql
-- Group by error message
SELECT
  LEFT(error_message, 50) as error,
  COUNT(*) as cnt
FROM workers.dead_letter_log
WHERE resolved_at IS NULL
GROUP BY 1
ORDER BY cnt DESC;
```

**Causes:**

- Bad deployment (code bug)
- Malformed input data (CSV issues)
- External service down (skip-trace API)

**Fix:**

1. Identify root cause from error messages
2. Fix code or data
3. Redeploy
4. Replay: `python -m tools.replay_dlq --yes`

---

## Quick Reference

### Commands Cheat Sheet

```bash
# Queue health
python -m tools.queue_inspect
python -m tools.queue_inspect --env prod --json

# DLQ management
python -m tools.replay_dlq --dry-run
python -m tools.replay_dlq --queue q_ingest_raw --yes

# Worker diagnostics
python -m tools.doctor --env prod
python -m tools.doctor_all --env prod

# Database checks
python -m tools.check_schema_consistency --env dev
```

### SQL Quick Queries

```sql
-- List all queues
SELECT * FROM pgmq.list_queues();

-- Queue metrics
SELECT * FROM pgmq.metrics_all();

-- Recent job completions
SELECT * FROM workers.processed_jobs
WHERE status = 'completed'
ORDER BY processed_at DESC
LIMIT 20;

-- Unresolved DLQ entries
SELECT * FROM workers.dead_letter_log
WHERE resolved_at IS NULL
ORDER BY moved_to_dlq_at DESC;
```

---

## Appendix: Migration Reference

Queue topology defined in: `supabase/migrations/20260110000000_queue_topology.sql`

Verify installation:

```sql
-- Should return 6 queues
SELECT * FROM pgmq.list_queues();

-- Should show workers schema objects
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'workers';
```

---

_This runbook is a living document. Update it when procedures change._
