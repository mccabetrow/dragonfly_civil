# RUNBOOK: Plaintiff Ingestion Pipeline

> **Version**: 2.0  
> **Date**: 2026-01-17  
> **Author**: Lead Principal Engineer

## Overview

This runbook covers the production-safe, idempotent plaintiff ingestion pipeline. The single operator entrypoint is `tools/plaintiff_ingest.py`.

## Key Guarantee

> **Upload same file twice = inserted 0 on second run.**

This is the core idempotency promise. The pipeline uses a three-layer defense:

1. **Batch-level**: `ingest.claim_import_run()` returns `duplicate` for already-processed batches
2. **Row-level**: `ON CONFLICT (dedupe_key) DO NOTHING` silently skips duplicates
3. **Reconciliation**: Verifies expected vs actual counts after every import

---

## Quick Reference

### Single Operator Command

```bash
# Dry run (default - validates without committing)
python -m tools.plaintiff_ingest \
    --csv data/plaintiffs.csv \
    --source-system simplicity \
    --source-batch-id batch-2026-01-17

# Commit to database
python -m tools.plaintiff_ingest \
    --csv data/plaintiffs.csv \
    --source-system simplicity \
    --source-batch-id batch-2026-01-17 \
    --commit
```

### Exit Codes

| Code | Meaning                        | Action                  |
| ---- | ------------------------------ | ----------------------- |
| 0    | Success (including duplicates) | None - all good         |
| 1    | Gate failure                   | Check logs, investigate |
| 2    | Script error                   | Fix file path or config |

### Parameters

| Parameter           | Required | Description                             |
| ------------------- | -------- | --------------------------------------- |
| `--csv`             | Yes      | Path to CSV file                        |
| `--source-system`   | Yes      | Source identifier (`simplicity`, `jbi`) |
| `--source-batch-id` | Yes      | Unique batch ID for idempotency         |
| `--commit`          | No       | Persist changes (default: dry-run)      |
| `--limit N`         | No       | Process only first N rows               |
| `--env`             | No       | Override `SUPABASE_MODE` (dev/prod)     |
| `--verbose`         | No       | Enable debug logging                    |

---

## Idempotency Proof

### Scenario: Upload Same File Twice

**First upload:**

```bash
$ python -m tools.plaintiff_ingest \
    --csv data/plaintiffs.csv \
    --source-system simplicity \
    --source-batch-id batch-001 \
    --commit

Database: host=*.pooler.supabase.com dbname=postgres user=postgres env=prod
File: plaintiffs.csv hash=a1b2c3d4e5f6... source=simplicity batch=batch-001
Claimed batch: run_id=550e8400-e29b-41d4-a716-446655440000
Inserted: fetched=100 inserted=100 skipped=0
Reconcile: PASS (expected=100 actual=100)
Transaction: COMMITTED

============================================================
PASS: run_id=550e8400-e29b-41d4-a716-446655440000 fetched=100 inserted=100 skipped=0 errored=0 reconcile=PASS
============================================================
```

**Second upload (same file):**

```bash
$ python -m tools.plaintiff_ingest \
    --csv data/plaintiffs.csv \
    --source-system simplicity \
    --source-batch-id batch-001 \
    --commit

Database: host=*.pooler.supabase.com dbname=postgres user=postgres env=prod
File: plaintiffs.csv hash=a1b2c3d4e5f6... source=simplicity batch=batch-001
Duplicate batch detected (run_id=550e8400-e29b-41d4-a716-446655440000). Already imported.

============================================================
PASS (duplicate): run_id=550e8400-e29b-41d4-a716-446655440000 - already imported
============================================================
```

**Result:** Exit 0, no rows inserted, no database changes.

---

## Pipeline Workflow

```
┌──────────────────────┐
│  1. Compute Hash     │  SHA-256 of file content
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  2. Claim Batch      │  ingest.claim_import_run()
└──────────┬───────────┘
           │
    ┌──────┼──────┐
    ▼      ▼      ▼
┌──────┐ ┌────────────┐ ┌───────────┐
│CLAIM │ │  DUPLICATE │ │IN_PROGRESS│
│  ED  │ │  Exit 0    │ │  Exit 1   │
└──┬───┘ └────────────┘ └───────────┘
   │
   ▼
┌──────────────────────┐
│  3. Insert Rows      │  ON CONFLICT DO NOTHING
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  4. Finalize Counts  │  Update import_runs
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  5. Reconcile        │  Compare expected vs actual
└──────────┬───────────┘
           │
    ┌──────┼──────┐
    ▼             ▼
┌──────┐     ┌──────┐
│ PASS │     │ FAIL │
│Exit 0│     │Exit 1│
└──────┘     └──────┘
```

---

## Security: Log Redaction

The pipeline automatically redacts PII patterns:

| Pattern                 | Redacted To       |
| ----------------------- | ----------------- |
| SSN (123-45-6789)       | `[SSN_REDACTED]`  |
| SSN (123456789)         | `[SSN_REDACTED]`  |
| Credit Card (16 digits) | `[CARD_REDACTED]` |

**SSNs and card numbers are NEVER logged, even in debug mode.**

```python
# This is automatic - no action required
logger.info("Processing SSN 123-45-6789")
# Logged as: "Processing SSN [SSN_REDACTED]"
```

---

## Troubleshooting

### "Another worker is processing"

**Symptom:** Exit code 1, `claim_status=in_progress`

**Cause:** Another worker has claimed the batch and is still processing.

**Resolution:**

1. Wait for the other worker to complete (check `ingest.import_runs`)
2. If stale (>30 min), the next claim will auto-takeover
3. Or manually abort:
   ```sql
   UPDATE ingest.import_runs
   SET status = 'failed',
       error_details = '{"manual_abort": true}'::jsonb
   WHERE source_batch_id = 'batch-001';
   ```

### "Reconciliation failed"

**Symptom:** `reconcile=FAIL`, `delta != 0`

**Cause:** Expected row count doesn't match actual rows in `plaintiffs_raw`.

**Resolution:**

1. Check for parse errors:
   ```sql
   SELECT * FROM ingest.plaintiffs_raw
   WHERE import_run_id = '<run_id>'
     AND status = 'failed';
   ```
2. Check for duplicates (skipped by `ON CONFLICT`):
   ```sql
   SELECT COUNT(*) FILTER (WHERE status = 'skipped') as skipped_count
   FROM ingest.plaintiffs_raw
   WHERE import_run_id = '<run_id>';
   ```
3. Verify CSV parsing is correct (encoding, delimiters)

### "Required tables not found"

**Symptom:** Exit code 2, "Required table not found"

**Cause:** Migrations have not been applied.

**Resolution:**

```bash
# Apply migrations
./scripts/db_push.ps1

# Verify
python -m tools.doctor --env dev
```

---

## Rollback a Bad Import

If you need to undo an import:

```sql
-- Soft-delete: marks run and rows as 'rolled_back'
SELECT * FROM ingest.rollback_import_run(
    '550e8400-e29b-41d4-a716-446655440000',  -- run_id
    'Data quality issue - vendor sent wrong file'
);
```

**Note:** Rollback does NOT delete data. All records are preserved for audit.

---

## Monitoring Queries

### Recent Imports

```sql
SELECT id, source_system, source_batch_id, status,
       rows_fetched, rows_inserted, rows_skipped, rows_errored,
       created_at
FROM ingest.import_runs
ORDER BY created_at DESC
LIMIT 20;
```

### Reconciliation Status

```sql
SELECT * FROM ingest.v_import_reconciliation
WHERE NOT is_reconciled;
```

### Duplicate Detection History

```sql
SELECT source_system, source_batch_id, file_hash,
       COUNT(*) as attempt_count,
       MIN(created_at) as first_attempt,
       MAX(created_at) as last_attempt
FROM ingest.import_runs
GROUP BY source_system, source_batch_id, file_hash
HAVING COUNT(*) > 1;
```

---

## Invariant Tests

Run the invariant tests to verify pipeline correctness:

```bash
pytest tests/test_plaintiff_ingest_invariants.py -v
```

These tests verify:

- Batch idempotency (same file → duplicate status)
- Row idempotency (same dedupe_key → skipped)
- Reconciliation correctness (expected == actual)
- Rollback behavior (soft-delete, audit preserved)

---

## CSV Format Requirements

The pipeline expects these columns (case-insensitive):

| Column           | Required | Notes               |
| ---------------- | -------- | ------------------- |
| `plaintiff_name` | Yes      | Or `name`           |
| `email`          | Yes      | Used for dedupe_key |
| `phone`          | No       |                     |
| `address`        | No       | Or `address_line1`  |
| `city`           | No       |                     |
| `state`          | No       |                     |
| `postal_code`    | No       | Or `zip`            |

**Dedupe Key Formula:**

```
SHA256(source_system || '|' || email.lower() || '|' || name.lower().strip())
```

---

## Related Documentation

- [RUNBOOK_PLAINTIFF_INGEST_MOAT.md](RUNBOOK_PLAINTIFF_INGEST_MOAT.md) - RPC function details
- [RUNBOOK_PLAINTIFF_INGESTION.md](RUNBOOK_PLAINTIFF_INGESTION.md) - Legacy importer docs
- [Migration: 20260115120000_plaintiff_ingest_claim_rpc.sql](../supabase/migrations/20260115120000_plaintiff_ingest_claim_rpc.sql) - Database schema
