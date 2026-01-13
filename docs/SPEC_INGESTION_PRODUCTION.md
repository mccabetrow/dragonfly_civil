# Dragonfly Ingestion Engine — Production Specification

**Version**: 1.0  
**Date**: 2026-01-09  
**Owner**: Data Platform Engineering

---

## 1. State Machine: `ingest.import_runs`

### 1.1 Status Enum

```sql
CREATE TYPE ingest.import_run_status AS ENUM (
    'pending',     -- Queued, not yet claimed
    'processing',  -- Claimed by a worker, actively running
    'completed',   -- Successfully finished
    'failed'       -- Terminal failure (moved to DLQ)
);
```

### 1.2 Valid State Transitions

```
┌─────────────┐
│   pending   │ ◄── Initial state (job queued)
└─────┬───────┘
      │ Worker claims job
      ▼
┌─────────────┐
│ processing  │ ◄── Worker is actively processing
└─────┬───────┘
      │
      ├──── Success ────► ┌───────────┐
      │                   │ completed │  (terminal)
      │                   └───────────┘
      │
      └──── Failure ────► ┌───────────┐
                          │  failed   │  (terminal, DLQ)
                          └───────────┘

      │
      └──── Stale (>1h) ──► Reset to 'pending' (takeover)
```

### 1.3 Transition Rules (Enforced in Worker)

| From State   | To State     | Condition                                     |
| ------------ | ------------ | --------------------------------------------- |
| `(none)`     | `pending`    | New batch, no existing record                 |
| `pending`    | `processing` | Worker claims with `INSERT...ON CONFLICT`     |
| `processing` | `completed`  | All records processed successfully            |
| `processing` | `failed`     | Unrecoverable exception thrown                |
| `processing` | `pending`    | Stale takeover: `started_at < NOW() - 1 hour` |
| `completed`  | _(blocked)_  | Immutable — idempotency guard                 |
| `failed`     | _(blocked)_  | Immutable — requires manual intervention      |

### 1.4 SQL Enforcement (Optional Trigger)

```sql
-- Prevent invalid transitions (defense in depth)
CREATE OR REPLACE FUNCTION ingest.guard_status_transition()
RETURNS TRIGGER AS $$
BEGIN
    -- Block transitions FROM terminal states
    IF OLD.status IN ('completed', 'failed') THEN
        RAISE EXCEPTION 'Cannot transition from terminal status: %', OLD.status;
    END IF;

    -- Block invalid transitions
    IF OLD.status = 'pending' AND NEW.status NOT IN ('processing') THEN
        RAISE EXCEPTION 'Invalid transition: pending -> %', NEW.status;
    END IF;

    IF OLD.status = 'processing' AND NEW.status NOT IN ('completed', 'failed', 'pending') THEN
        RAISE EXCEPTION 'Invalid transition: processing -> %', NEW.status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_import_runs_status_guard
    BEFORE UPDATE ON ingest.import_runs
    FOR EACH ROW
    EXECUTE FUNCTION ingest.guard_status_transition();
```

---

## 2. Stale-Lock Takeover Rules

### 2.1 Problem Statement

A worker may crash, lose connectivity, or be killed while `status='processing'`. Without intervention, the batch would be stuck forever.

### 2.2 Takeover Logic

**Threshold**: `PROCESSING_TIMEOUT_HOURS = 1`

```python
# In IngestWorker.process()
if existing.is_processing and existing.is_stale:
    # Stale = started_at < NOW() - 1 hour
    logger.warning(f"[STALE TAKEOVER] Batch {source_batch_id} abandoned for >{PROCESSING_TIMEOUT_HOURS}h")

    # Reset to pending so we can reclaim
    cur.execute("""
        UPDATE ingest.import_runs
        SET status = 'pending'
        WHERE source_batch_id = %s
          AND status = 'processing'
          AND started_at < NOW() - INTERVAL '1 hour'
    """, (source_batch_id,))
```

### 2.3 Safety Guarantees

| Guarantee                | Implementation                                                         |
| ------------------------ | ---------------------------------------------------------------------- |
| **No double-processing** | Reset to `pending` first, then reclaim with `processing`               |
| **No lost updates**      | `WHERE status = 'processing'` ensures only stale jobs are touched      |
| **Audit trail**          | Log takeover with batch ID, original `started_at`, worker ID           |
| **Alerting**             | Discord notification on every takeover (potential crash investigation) |

### 2.4 SQL View for Monitoring Stale Runs

```sql
CREATE OR REPLACE VIEW ingest.v_stale_runs AS
SELECT
    id,
    source_batch_id,
    status,
    started_at,
    EXTRACT(EPOCH FROM (NOW() - started_at)) / 3600 AS hours_stale,
    file_hash
FROM ingest.import_runs
WHERE status = 'processing'
  AND started_at < NOW() - INTERVAL '1 hour'
ORDER BY started_at ASC;

COMMENT ON VIEW ingest.v_stale_runs IS 'Import runs stuck in processing state for >1 hour (potential crash victims).';
```

---

## 3. Unique Constraints for Idempotency

### 3.1 Required Constraints

| Table                              | Constraint                       | Purpose                             |
| ---------------------------------- | -------------------------------- | ----------------------------------- |
| `ingest.import_runs`               | `UNIQUE (source_batch_id)`       | One tracking row per batch          |
| `public.judgments`                 | `UNIQUE (case_number)`           | Prevent duplicate case records      |
| `public.plaintiffs`                | `UNIQUE (dedupe_key)`            | Prevent duplicate plaintiff records |
| `intake.simplicity_validated_rows` | `UNIQUE (batch_id, case_number)` | Prevent duplicate staging rows      |

### 3.2 Upsert Pattern (Worker Implementation)

```python
# Judgment upsert with ON CONFLICT
cur.execute("""
    INSERT INTO public.judgments (
        case_number, plaintiff_name, defendant_name,
        judgment_amount, filing_date, county, source_file
    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (case_number) DO UPDATE SET
        plaintiff_name = COALESCE(EXCLUDED.plaintiff_name, judgments.plaintiff_name),
        defendant_name = COALESCE(EXCLUDED.defendant_name, judgments.defendant_name),
        judgment_amount = COALESCE(EXCLUDED.judgment_amount, judgments.judgment_amount),
        filing_date = COALESCE(EXCLUDED.filing_date, judgments.filing_date),
        county = COALESCE(EXCLUDED.county, judgments.county),
        updated_at = NOW()
    RETURNING (xmax = 0) AS is_insert
""", (...))
```

**Key**: `RETURNING (xmax = 0) AS is_insert` tells you if it was an INSERT (true) or UPDATE (false).

### 3.3 Dedupe Key Generation for Plaintiffs

```python
def generate_dedupe_key(name: str, email: str | None, phone: str | None) -> str:
    """Generate a stable dedupe key for plaintiff matching."""
    # Normalize name: lowercase, strip whitespace, remove punctuation
    normalized_name = re.sub(r'[^a-z0-9]', '', name.lower())

    # Use email if available (strongest identifier)
    if email:
        return f"email:{email.lower().strip()}"

    # Use phone if available
    if phone:
        digits = re.sub(r'\D', '', phone)[-10:]  # Last 10 digits
        return f"phone:{digits}"

    # Fallback to name hash
    return f"name:{hashlib.md5(normalized_name.encode()).hexdigest()[:16]}"
```

---

## 4. Golden Path Test Plan

### 4.1 Test Matrix

| Test Case                   | Dev | Prod | Expected Outcome                         |
| --------------------------- | --- | ---- | ---------------------------------------- |
| Fresh batch ingestion       | ✓   | ✓    | `status='completed'`, `record_count=1`   |
| Duplicate batch rejection   | ✓   | ✓    | No update, logs "Skipping duplicate"     |
| Stale takeover              | ✓   | —    | Reset to `pending`, reprocess            |
| Unique constraint violation | ✓   | —    | `ON CONFLICT` triggers update, not error |

### 4.2 Dev Environment Test

```bash
# Run the automated golden path test
python -m tools.verify_ingest_golden_path --env dev
```

**Expected Output**:

```
  Initial Completion: PASS
  Duplicate Skip:     PASS
  Cleanup:            PASS
  [SUCCESS] Golden Path Verified - Data Moat is operational!
```

### 4.3 SQL Verification Queries

#### Check 1: Import Run Created

```sql
SELECT id, source_batch_id, status, record_count,
       started_at, completed_at
FROM ingest.import_runs
WHERE source_batch_id = 'golden_path_test_%'
ORDER BY started_at DESC
LIMIT 1;

-- Expected: status='completed', record_count=1
```

#### Check 2: No Stale Runs

```sql
SELECT COUNT(*) AS stale_count
FROM ingest.v_stale_runs;

-- Expected: 0
```

#### Check 3: Unique Constraints Active

```sql
SELECT
    tc.constraint_name,
    tc.table_schema,
    tc.table_name,
    kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
WHERE tc.constraint_type = 'UNIQUE'
  AND tc.table_name IN ('judgments', 'plaintiffs', 'import_runs')
ORDER BY tc.table_name;

-- Expected: case_number (judgments), dedupe_key (plaintiffs), source_batch_id (import_runs)
```

#### Check 4: Idempotency Test

```sql
-- Insert same case twice - should not error
INSERT INTO public.judgments (case_number, plaintiff_name)
VALUES ('TEST-IDEMPOTENCY-001', 'Test Plaintiff')
ON CONFLICT (case_number) DO UPDATE SET updated_at = NOW()
RETURNING (xmax = 0) AS was_insert;

-- First run: was_insert = true
-- Second run: was_insert = false
```

### 4.4 Production Verification (Post-Deploy)

```bash
# Dry-run first (no data changes)
python -m tools.verify_ingest_golden_path --env prod --dry-run

# Actual test (with confirmation prompt)
python -m tools.verify_ingest_golden_path --env prod
```

---

## 5. Logging & Alerting Requirements

### 5.1 MUST Log (Structured JSON)

| Event             | Log Level | Fields                                                                  |
| ----------------- | --------- | ----------------------------------------------------------------------- |
| Job started       | `INFO`    | `source_batch_id`, `file_hash`, `worker_id`                             |
| Job completed     | `INFO`    | `source_batch_id`, `record_count`, `inserted`, `updated`, `duration_ms` |
| Job failed        | `ERROR`   | `source_batch_id`, `error_type`, `error_message` (truncated)            |
| Duplicate skipped | `INFO`    | `source_batch_id`, `reason="duplicate_completed"`                       |
| Stale takeover    | `WARNING` | `source_batch_id`, `stale_hours`, `original_started_at`                 |
| Row-level error   | `WARNING` | `source_batch_id`, `row_number`, `error_type` (no PII)                  |

### 5.2 MUST Alert (Discord/PagerDuty)

| Condition               | Severity  | Alert Message                                               |
| ----------------------- | --------- | ----------------------------------------------------------- |
| Job failed (terminal)   | `ERROR`   | `[INGEST FAILURE] {source_batch_id}: {error_type}`          |
| Stale takeover occurred | `WARNING` | `[STALE TAKEOVER] {source_batch_id} abandoned for {hours}h` |
| DLQ depth > 5           | `WARNING` | `Ingest dead-letter queue has {count} messages`             |
| Backlog > 100           | `WARNING` | `Ingest backlog at {count} pending jobs`                    |

### 5.3 MUST NEVER Log

| Sensitive Data                        | Reason                         |
| ------------------------------------- | ------------------------------ |
| Full plaintiff names                  | PII - FCRA compliance          |
| Email addresses                       | PII                            |
| Phone numbers                         | PII                            |
| Social Security Numbers               | PII - never in system          |
| Full file contents                    | Data exposure risk             |
| Database connection strings           | Credential exposure            |
| JWT tokens / API keys                 | Credential exposure            |
| Full stack traces to external systems | Internal architecture exposure |

### 5.4 Redaction Pattern

```python
# In logging configuration
SENSITIVE_PATTERNS = [
    (r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+', '[JWT_REDACTED]'),
    (r'postgresql://[^@]+@', 'postgresql://[REDACTED]@'),
    (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN_REDACTED]'),
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL_REDACTED]'),
]
```

---

## 6. Operational Metrics (Dashboard)

These are exposed via `/api/metrics`:

```json
{
  "ingest": {
    "backlog_count": 3,
    "last_failed_batch": "simplicity-2026-01-07.csv",
    "last_failed_at": "2026-01-07T14:32:00Z"
  }
}
```

### 6.1 Key Metrics

| Metric              | Query                                                                                                            | Alert Threshold |
| ------------------- | ---------------------------------------------------------------------------------------------------------------- | --------------- |
| Backlog             | `SELECT COUNT(*) FROM ingest.import_runs WHERE status IN ('pending', 'processing')`                              | > 100           |
| Failed (24h)        | `SELECT COUNT(*) FROM ingest.import_runs WHERE status = 'failed' AND completed_at > NOW() - '24h'`               | > 0             |
| Stale runs          | `SELECT COUNT(*) FROM ingest.v_stale_runs`                                                                       | > 0             |
| Avg processing time | `SELECT AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) FROM ingest.import_runs WHERE status = 'completed'` | > 300s          |

---

## 7. Appendix: Migration Checklist

### Before Production Deploy

- [ ] Migration `20261101_ingestion_idempotency.sql` applied to prod
- [ ] `ingest.import_runs` table exists with correct schema
- [ ] `UNIQUE (source_batch_id)` constraint active
- [ ] `UNIQUE (case_number)` on `public.judgments` active
- [ ] `UNIQUE (dedupe_key)` on `public.plaintiffs` active
- [ ] Service role has `SELECT, INSERT, UPDATE` on `ingest.import_runs`
- [ ] RLS enabled and policy for `service_role` exists
- [ ] Worker deployed with `PROCESSING_TIMEOUT_HOURS = 1`
- [ ] Discord webhook configured for alerts
- [ ] Golden path test passes in dev

### Post-Deploy Verification

```bash
# 1. Check schema
python -m tools.doctor_all --env prod

# 2. Run golden path test
python -m tools.verify_ingest_golden_path --env prod

# 3. Monitor for 24h
# - Watch /api/metrics for backlog
# - Check Discord for alerts
# - Verify no stale runs accumulate
```

---

**System Status**: Production-ready with exactly-once semantics, crash recovery, and full observability.
