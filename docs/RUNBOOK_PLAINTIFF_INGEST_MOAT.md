# RUNBOOK: Plaintiff Ingestion Moat

> **Version**: 1.0  
> **Date**: 2026-01-15  
> **Author**: Principal Database Reliability Engineer

## Overview

The Plaintiff Ingestion Moat is a production-grade system for idempotent, auditable plaintiff data ingestion. It prevents duplicate imports, provides concurrency safety, and maintains a full audit trail.

## Architecture

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│   CSV File      │────▶│  claim_import_run()  │────▶│  ingest.        │
│   (source)      │     │  (atomic claim)      │     │  import_runs    │
└─────────────────┘     └──────────────────────┘     └─────────────────┘
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │  Claim Status:       │
                        │  • claimed           │──────▶ Proceed with import
                        │  • duplicate         │──────▶ Exit 0 (already done)
                        │  • in_progress       │──────▶ Exit 1 (retry later)
                        └──────────────────────┘
                                   │
                                   ▼ (if claimed)
                        ┌──────────────────────┐
                        │  Process CSV rows    │
                        │  Insert to DB        │
                        └──────────────────────┘
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │  finalize_import_run │
                        │  (update counts)     │
                        └──────────────────────┘
```

## Key Components

| Component         | Location                                                            | Purpose                                    |
| ----------------- | ------------------------------------------------------------------- | ------------------------------------------ |
| SQL Migration     | `supabase/migrations/20260115120000_plaintiff_ingest_claim_rpc.sql` | RPC functions for claim/reconcile/rollback |
| Python Client     | `etl/src/ingest_claim.py`                                           | Python wrapper for RPC functions           |
| Enhanced Importer | `etl/src/plaintiff_importer_moat.py`                                | CSV importer with moat integration         |
| Log Redactor      | `etl/src/log_redactor.py`                                           | PII redaction for logs                     |
| Operator Queries  | `ops/queries/plaintiff_ingest_moat.sql`                             | Monitoring and troubleshooting             |

## RPC Functions

### `ingest.claim_import_run()`

Atomically claim an import batch. Call this BEFORE processing any rows.

```sql
SELECT * FROM ingest.claim_import_run(
    'simplicity',           -- source_system
    'batch-2026-01-15',     -- source_batch_id
    'abc123def456...',      -- file_hash (SHA-256)
    'plaintiffs.csv',       -- filename
    'plaintiff',            -- import_kind
    'worker-1'              -- worker_id
);
```

**Returns**: `(run_id uuid, claim_status text)`

| claim_status  | Meaning               | Action               |
| ------------- | --------------------- | -------------------- |
| `claimed`     | Successfully claimed  | Proceed with import  |
| `duplicate`   | Already completed     | Exit 0 (no-op)       |
| `in_progress` | Another worker has it | Exit 1 (retry later) |

### `ingest.reconcile_import_run()`

Verify row counts after import. Marks run as completed or failed.

```sql
SELECT * FROM ingest.reconcile_import_run(
    '123e4567-e89b-12d3-a456-426614174000',  -- run_id
    100                                       -- expected_count (optional)
);
```

**Returns**: `(is_valid boolean, expected_count int, actual_count int, delta int)`

### `ingest.rollback_import_run()`

Soft-delete a run. Marks associated rows as rolled_back (no hard delete).

```sql
SELECT * FROM ingest.rollback_import_run(
    '123e4567-e89b-12d3-a456-426614174000',  -- run_id
    'Data quality issue discovered'           -- reason
);
```

**Returns**: `(success boolean, rows_affected int)`

### `ingest.finalize_import_run()`

Update run with final counts. Called by Python importer.

```sql
SELECT ingest.finalize_import_run(
    run_id,
    rows_fetched,
    rows_inserted,
    rows_skipped,
    rows_errored,
    error_details,      -- jsonb (set {"fatal": true} for failures)
    mark_completed      -- boolean
);
```

### `ingest.heartbeat_import_run()`

Keep claim alive during long imports. Prevents stale takeover.

```sql
SELECT ingest.heartbeat_import_run('123e4567-e89b-12d3-a456-426614174000');
```

## Python Usage

### Basic Import with Moat

```python
from etl.src.ingest_claim import IngestClaimClient, compute_file_hash, ClaimStatus
import psycopg

with psycopg.connect(dsn) as conn:
    client = IngestClaimClient(conn)

    # 1. Claim the batch
    file_hash = compute_file_hash("plaintiffs.csv")
    claim = client.claim(
        source_system="simplicity",
        source_batch_id="batch-2026-01-15",
        file_hash=file_hash,
        filename="plaintiffs.csv",
    )

    if claim.is_duplicate:
        print("Already imported")
        sys.exit(0)

    if claim.is_in_progress:
        print("Another worker processing")
        sys.exit(1)

    # 2. Process the file
    try:
        rows_inserted = process_csv(...)

        # 3. Finalize with counts
        client.finalize(
            run_id=claim.run_id,
            rows_fetched=100,
            rows_inserted=rows_inserted,
            rows_skipped=0,
            rows_errored=0,
        )
    except Exception as e:
        client.finalize(
            run_id=claim.run_id,
            rows_fetched=0,
            rows_inserted=0,
            rows_skipped=0,
            rows_errored=1,
            error_details={"fatal": True, "message": str(e)},
        )
        raise
```

### CLI Usage

```bash
# Dry run (default)
python -m etl.src.plaintiff_importer_moat --csv data/plaintiffs.csv

# Commit changes
python -m etl.src.plaintiff_importer_moat --csv data/plaintiffs.csv --commit

# With explicit source system
python -m etl.src.plaintiff_importer_moat \
    --csv data/simplicity_export.csv \
    --source-system simplicity \
    --commit
```

## Log Redaction

All logs automatically redact SSN and credit card patterns.

```python
from etl.src.log_redactor import SafeLogger, redact
import logging

# Wrap your logger
logger = SafeLogger(logging.getLogger(__name__))

# SSN is redacted
logger.info("Processing SSN 123-45-6789")
# Logged as: "Processing SSN [SSN_REDACTED]"

# Card is redacted
logger.info("Card: 4111-1111-1111-1111")
# Logged as: "Card: [CARD_REDACTED]"
```

## Operator Procedures

### Check Recent Import Activity

```sql
-- Last 20 runs
SELECT * FROM ingest.v_latest_runs;

-- Or use full query from ops/queries/plaintiff_ingest_moat.sql
```

### Investigate Failed Import

1. Find the failed run:

```sql
SELECT * FROM ingest.import_runs
WHERE id = '<run_id>';
```

2. Check error details:

```sql
SELECT error_details FROM ingest.import_runs
WHERE id = '<run_id>';
```

3. Check row-level errors:

```sql
SELECT * FROM ingest.plaintiffs_raw
WHERE import_run_id = '<run_id>'
  AND status = 'failed';
```

### Rollback a Bad Import

```sql
SELECT * FROM ingest.rollback_import_run(
    '<run_id>',
    'Reason for rollback'
);
```

Verify rollback:

```sql
SELECT * FROM ingest.v_rollback_verification
WHERE id = '<run_id>';
```

### Handle Stale Worker

If a worker crashes mid-import, the run becomes "stale" after 30 minutes.
A new worker can take over automatically.

Check stale runs:

```sql
SELECT *
FROM ingest.import_runs
WHERE status = 'processing'
  AND updated_at < now() - interval '30 minutes';
```

### Re-import After Rollback

1. First rollback the existing run
2. Claim will return `claimed` for the same batch (failed/rolled_back runs can be re-claimed)

## Monitoring Queries

All queries are in `ops/queries/plaintiff_ingest_moat.sql`:

| Query                   | Purpose                     |
| ----------------------- | --------------------------- |
| Latest Runs             | Recent import activity      |
| Duplicates Blocked      | Rejected duplicate attempts |
| Reconciliation Failures | Row count mismatches        |
| Rollback Verification   | Rolled back runs            |
| In-Progress Runs        | Currently processing        |
| Failed Runs             | Error details               |
| Source System Stats     | Aggregate metrics           |

## Troubleshooting

### "Another worker is processing"

**Symptom**: Import returns `in_progress` status

**Causes**:

1. Another worker is legitimately processing the batch
2. Previous worker crashed and claim is stale

**Resolution**:

1. Check if another import is actually running
2. Wait 30 minutes for stale takeover
3. Or manually update the run status:
   ```sql
   UPDATE ingest.import_runs
   SET status = 'failed',
       error_details = '{"manual_abort": true}'::jsonb
   WHERE id = '<run_id>';
   ```

### "Reconciliation Failed"

**Symptom**: `is_valid = false` from reconcile

**Causes**:

1. Some rows failed to insert
2. Duplicate rows were skipped
3. Count mismatch in CSV parsing

**Resolution**:

1. Check row-level errors in `ingest.plaintiffs_raw`
2. Verify `dedupe_key` computation is deterministic
3. Re-run import after fixing data issues

### "SSN appears in logs"

**This should never happen** due to log redaction.

**If it does**:

1. Check that SafeLogger is being used
2. Verify PIIRedactionFilter is applied to root logger
3. Run log redaction tests: `pytest etl/tests/test_log_redactor.py -v`

## Deployment Checklist

1. [ ] Apply migration: `./scripts/db_push.ps1 -SupabaseEnv dev`
2. [ ] Verify RPC functions exist:
   ```sql
   SELECT routine_name FROM information_schema.routines
   WHERE routine_schema = 'ingest';
   ```
3. [ ] Test claim/finalize cycle in dev
4. [ ] Run log redaction tests
5. [ ] Apply to prod: `./scripts/db_push.ps1 -SupabaseEnv prod`

## Security Notes

- **dragonfly_app** role has execute on all ingest RPC functions
- Log redaction is enforced at the Python layer
- No PII should ever appear in `ingest.import_runs.error_details`
- All rollbacks are soft-deletes (audit trail preserved)
