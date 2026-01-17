# Plaintiff Ingestion Runbook

**Version:** 1.0.0  
**Last Updated:** 2025-01-14  
**Owner:** Dragonfly Engineering

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start: Importing a File](#quick-start-importing-a-file)
3. [Idempotency Guarantees](#idempotency-guarantees)
4. [Proving Idempotency](#proving-idempotency)
5. [Monitoring Import Runs](#monitoring-import-runs)
6. [Reconciliation](#reconciliation)
7. [Rollback a Bad Batch](#rollback-a-bad-batch)
8. [Troubleshooting](#troubleshooting)
9. [SQL Reference](#sql-reference)

---

## Overview

The Plaintiff Intake Moat is an **enterprise-grade, idempotent ingestion pipeline** for importing plaintiff records into the Dragonfly system.

### Key Guarantees

| Guarantee                   | Mechanism                                           | Scope                    |
| --------------------------- | --------------------------------------------------- | ------------------------ |
| **Batch-level idempotency** | `UNIQUE(source_system, source_batch_id, file_hash)` | Same file → no-op        |
| **Row-level idempotency**   | `UNIQUE(dedupe_key)` on `plaintiffs_raw`            | Same plaintiff → skipped |
| **Atomic claiming**         | `ingest.claim_import_run()` RPC                     | Concurrency-safe         |
| **PII protection**          | `sanitize_for_log()` redaction                      | SSN never logged         |

### Architecture

```
CSV File
   │
   ▼
┌─────────────────────────────────────────────────────────────────┐
│  PlaintiffIntakePipeline                                        │
│  ┌──────────────────┐    ┌──────────────────┐                   │
│  │ compute_file_hash│───▶│ claim_import_run │ ◄── RPC (atomic)  │
│  └──────────────────┘    └──────────────────┘                   │
│          │                       │                              │
│          ▼                       ▼                              │
│  ┌──────────────────┐    ┌──────────────────┐                   │
│  │   parse_csv      │───▶│  insert_rows     │ ◄── ON CONFLICT   │
│  └──────────────────┘    └──────────────────┘     DO NOTHING    │
└─────────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────────┐
│  ingest.plaintiffs_raw  (landing zone)                          │
│  status: pending → processing → promoted/failed/skipped         │
└─────────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────────┐
│  public.plaintiffs  (production table)                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Start: Importing a File

### Step 1: Validate the File (Dry Run)

Always dry-run first to catch parsing errors:

```powershell
# Windows (PowerShell)
$env:SUPABASE_MODE = "dev"
.\.venv\Scripts\python.exe -m backend.ingest.intake_csv `
    --file data_in/plaintiffs.csv `
    --source simplicity `
    --dry-run
```

Expected output:

```
2025-01-14 10:30:00 [INFO] [intake] Starting import: file=plaintiffs.csv source=simplicity hash=a1b2c3...
2025-01-14 10:30:00 [INFO] [intake] Dry run complete: Import DRY_RUN: 100 fetched, 100 inserted, 0 skipped, 0 errored

============================================================
Import DRY_RUN: 100 fetched, 100 inserted, 0 skipped, 0 errored
============================================================
```

### Step 2: Execute the Import

```powershell
$env:SUPABASE_MODE = "dev"  # or "prod" for production
.\.venv\Scripts\python.exe -m backend.ingest.intake_csv `
    --file data_in/plaintiffs.csv `
    --source simplicity
```

### Step 3: Verify

```sql
-- Check the import run
SELECT * FROM ingest.v_import_runs_summary
WHERE filename = 'plaintiffs.csv'
ORDER BY created_at DESC
LIMIT 1;

-- Check for discrepancies
SELECT * FROM ingest.v_import_reconciliation
WHERE filename = 'plaintiffs.csv'
  AND NOT is_reconciled;
```

---

## Idempotency Guarantees

### Batch-Level: Same File = No-Op

If you import the exact same file twice, the second import is a **no-op**:

```
First import:  "claimed" → inserts rows
Second import: "duplicate" → returns immediately, zero rows touched
```

The triple `(source_system, source_batch_id, file_hash)` must be unique.

### Row-Level: Same Plaintiff = Skipped

Even within a new file, if a plaintiff already exists (by dedupe key), the row is **skipped**:

```
Dedupe key = SHA-256(source_system | normalized_name | normalized_email)
```

Example:

- File 1: `John Doe, john@example.com` → inserted
- File 2: `JOHN DOE, JOHN@EXAMPLE.COM` → **skipped** (same dedupe key)

---

## Proving Idempotency

### Test 1: Re-import Same File

```powershell
# First import
.\.venv\Scripts\python.exe -m backend.ingest.intake_csv --file test.csv --source test

# Second import (should be instant no-op)
.\.venv\Scripts\python.exe -m backend.ingest.intake_csv --file test.csv --source test
```

Expected:

```
DUPLICATE BATCH: File 'test.csv' with hash abc123... has already been imported. No action taken.
```

### Test 2: Verify No Duplicate Rows

```sql
-- Check for duplicate dedupe keys (should return 0)
SELECT dedupe_key, COUNT(*) as cnt
FROM ingest.plaintiffs_raw
GROUP BY dedupe_key
HAVING COUNT(*) > 1;
```

### Test 3: Verify Hash Consistency

```python
from backend.ingest.intake_csv import compute_file_hash_from_path
from pathlib import Path

# Same file = same hash
hash1 = compute_file_hash_from_path(Path("test.csv"))
hash2 = compute_file_hash_from_path(Path("test.csv"))
assert hash1 == hash2  # Always true

# Copy = same hash
import shutil
shutil.copy("test.csv", "test_copy.csv")
hash3 = compute_file_hash_from_path(Path("test_copy.csv"))
assert hash1 == hash3  # Content-based, not filename-based
```

---

## Monitoring Import Runs

### View Recent Imports

```sql
SELECT
    id,
    source_system,
    filename,
    status,
    rows_fetched,
    rows_inserted,
    rows_skipped,
    rows_errored,
    duration_seconds,
    created_at
FROM ingest.v_import_runs_summary
ORDER BY created_at DESC
LIMIT 20;
```

### View Failed Rows

```sql
SELECT
    filename,
    row_index,
    plaintiff_name,
    error_code,
    error_message
FROM ingest.v_errored_rows
WHERE import_run_id = 'YOUR-RUN-ID-HERE'
ORDER BY row_index;
```

### View Duplicates Blocked

```sql
SELECT
    dedupe_key,
    plaintiff_name,
    source_system,
    filename,
    created_at
FROM ingest.v_blocked_duplicates
WHERE filename = 'plaintiffs.csv';
```

---

## Reconciliation

Reconciliation ensures reported counts match actual database rows.

### Quick Check

```sql
SELECT * FROM ingest.v_import_reconciliation
WHERE NOT is_reconciled
ORDER BY created_at DESC;
```

### Detailed Reconciliation

```sql
SELECT * FROM ingest.reconcile_import_run('YOUR-RUN-ID-HERE');
```

Returns:
| Column | Description |
|--------|-------------|
| `reported_inserted` | What the pipeline reported |
| `actual_total` | Actual rows in `plaintiffs_raw` |
| `inserted_discrepancy` | Difference (should be 0) |
| `is_reconciled` | `true` if no discrepancy |

### Investigate Discrepancies

If `is_reconciled = false`:

1. **Check for orphaned rows:**

   ```sql
   SELECT * FROM ingest.plaintiffs_raw
   WHERE import_run_id = 'YOUR-RUN-ID'
     AND status NOT IN ('pending', 'promoted');
   ```

2. **Check for missing rows:**

   ```sql
   -- Row count should match rows_fetched
   SELECT COUNT(*) FROM ingest.plaintiffs_raw
   WHERE import_run_id = 'YOUR-RUN-ID';
   ```

3. **Check for constraint violations:**
   ```sql
   SELECT * FROM ingest.v_errored_rows
   WHERE import_run_id = 'YOUR-RUN-ID';
   ```

---

## Rollback a Bad Batch

### When to Rollback

- Vendor sent corrupted data
- Wrong source system tag
- Data quality issues discovered post-import

### Soft-Delete (Recommended)

Preserves audit trail while marking records as rolled back:

```sql
SELECT * FROM ingest.rollback_import_run(
    'YOUR-RUN-ID-HERE',
    'Reason: Vendor sent test data in production - Ticket #1234'
);
```

This:

1. Marks `import_runs.status` = `'rolled_back'`
2. Stores rollback reason in `error_details`
3. Marks all `plaintiffs_raw` rows with `status = 'rolled_back'`

### Verify Rollback

```sql
-- Check run status
SELECT id, status, error_details->'rollback_reason' as reason
FROM ingest.import_runs
WHERE id = 'YOUR-RUN-ID';

-- Check row status
SELECT status, COUNT(*)
FROM ingest.plaintiffs_raw
WHERE import_run_id = 'YOUR-RUN-ID'
GROUP BY status;
```

### Hard Delete (Extreme Cases Only)

**⚠️ DANGER: Only if soft-delete is insufficient and approved by engineering lead.**

```sql
-- Step 1: Delete raw rows
DELETE FROM ingest.plaintiffs_raw
WHERE import_run_id = 'YOUR-RUN-ID';

-- Step 2: Delete import run
DELETE FROM ingest.import_runs
WHERE id = 'YOUR-RUN-ID';
```

**Note:** After hard delete, you CAN re-import the same file (the unique constraint is gone).

---

## Troubleshooting

### Error: "Duplicate batch, skipping"

**Cause:** File has already been imported (same source + batch_id + hash).

**Fix:**

- If intentional re-import: Use a different `--batch-id`
- If testing: Delete the import run first (dev only)

### Error: "Missing required columns: {'plaintiff_name'}"

**Cause:** CSV headers don't map to required columns.

**Fix:** Check `CANONICAL_HEADERS` in `intake_csv.py` for accepted aliases:

- `PlaintiffName`, `plaintiff_name`, `name`, `Name`, `plaintiff`

### Error: "FATAL: Tenant or user not found"

**Cause:** Database connection string has wrong username format for pooler.

**Fix:** See `docs/RUNBOOK_POOLER_IDENTITY.md` for Supabase pooler identity rules.

### High Skip Rate

**Cause:** Many plaintiffs already exist (by dedupe key).

**Investigation:**

```sql
-- Check what's being skipped
SELECT pr.plaintiff_name, pr.dedupe_key
FROM ingest.plaintiffs_raw pr
WHERE pr.import_run_id = 'YOUR-RUN-ID'
  AND pr.status = 'skipped';

-- Find the original record
SELECT * FROM ingest.plaintiffs_raw
WHERE dedupe_key = 'the-skipped-dedupe-key'
ORDER BY created_at;
```

---

## SQL Reference

### Functions

| Function                                                          | Purpose                           |
| ----------------------------------------------------------------- | --------------------------------- |
| `ingest.claim_import_run(source, batch_id, hash, filename, kind)` | Atomic import run claim           |
| `ingest.reconcile_import_run(run_id)`                             | Compare reported vs actual counts |
| `ingest.rollback_import_run(run_id, reason)`                      | Soft-delete import run            |
| `ingest.compute_plaintiff_dedupe_key(source, name, email)`        | Compute dedupe key (SQL-side)     |

### Views

| View                             | Purpose                      |
| -------------------------------- | ---------------------------- |
| `ingest.v_import_runs_summary`   | Recent imports with duration |
| `ingest.v_import_reconciliation` | Bulk reconciliation status   |
| `ingest.v_blocked_duplicates`    | Records blocked by dedup     |
| `ingest.v_errored_rows`          | Failed records with errors   |

### Tables

| Table                   | Purpose                      |
| ----------------------- | ---------------------------- |
| `ingest.import_runs`    | Import run metadata          |
| `ingest.plaintiffs_raw` | Landing zone for raw records |
| `public.plaintiffs`     | Production plaintiff records |

---

## Appendix: Dedupe Key Computation

The dedupe key ensures the same plaintiff is never inserted twice, even across different imports.

```
dedupe_key = SHA-256(
    source_system          + "|" +
    normalized_name        + "|" +
    normalized_email
)
```

Where:

- `normalized_name` = `lowercase(trim(collapse_whitespace(name)))`
- `normalized_email` = `lowercase(trim(email))` or empty string if null

### Examples

| Source     | Name     | Email            | Dedupe Key (first 16 chars)            |
| ---------- | -------- | ---------------- | -------------------------------------- |
| simplicity | John Doe | john@example.com | `a1b2c3d4e5f6g7h8`                     |
| simplicity | JOHN DOE | JOHN@EXAMPLE.COM | `a1b2c3d4e5f6g7h8` (same!)             |
| simplicity | John Doe | john@example.com | `a1b2c3d4e5f6g7h8` (same!)             |
| jbi        | John Doe | john@example.com | `z9y8x7w6v5u4t3s2` (different source!) |

---

_For questions, contact the Dragonfly Engineering team or file an issue in the repository._
