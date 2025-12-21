# Worker Security Model

This document describes the security model for Dragonfly Civil worker processes.

## Overview

Workers execute background tasks like CSV ingestion, enforcement calculations, and data validation. They operate under a **least-privilege** model where:

1. **Workers connect as `dragonfly_app`** - a restricted database role
2. **`dragonfly_app` has SELECT-only access** to protected tables
3. **All writes go through SECURITY DEFINER functions** - RPC endpoints owned by `postgres`

## Why This Is Safer

### Before (Vulnerable)

```python
# Worker had direct table access - security risk!
cur.execute("""
    INSERT INTO ops.job_queue (payload, status) VALUES (%s, 'pending')
""", [json.dumps(data)])
```

Problems with direct SQL:

- Any SQL injection vulnerability grants full table access
- Workers can accidentally DELETE or UPDATE wrong rows
- No audit trail for who/what modified data
- Schema changes require updating every worker

### After (Secure)

```python
# Worker calls RPC - controlled entry point
rpc.queue_job(payload=data, job_type="ingest")
```

Benefits of RPC-only writes:

- **Least Privilege**: Workers can only perform operations we explicitly allow
- **Input Validation**: RPCs validate parameters before writing
- **Audit Trail**: RPC functions log who called them and when
- **Schema Independence**: Internal table structure can change without breaking workers
- **SQL Injection Resistant**: RPC parameters are bound, never concatenated

## Protected Schemas

The following schemas have INSERT/UPDATE/DELETE **revoked** from `dragonfly_app`:

| Schema        | Tables                                                    | Why Protected                                                  |
| ------------- | --------------------------------------------------------- | -------------------------------------------------------------- |
| `ops`         | job_queue, intake_logs, worker_heartbeats, ingest_batches | Operational integrity - job state must be consistent           |
| `intake`      | foil_datasets, foil_raw_rows, foil_quarantine             | Data lineage - every row must be traceable                     |
| `public`      | judgments, plaintiffs, enforcement_cases                  | Business critical - writes must go through validated pipelines |
| `enforcement` | All tables                                                | Enforcement state - legal accuracy required                    |

## SECURITY DEFINER Functions

Each protected write operation has a dedicated RPC:

### ops Schema

| RPC                                             | Purpose                |
| ----------------------------------------------- | ---------------------- |
| `ops.claim_pending_job(worker_id, job_types[])` | Atomically claim a job |
| `ops.update_job_status(job_id, status, ...)`    | Update job progress    |
| `ops.queue_job(job_type, payload)`              | Create new job         |
| `ops.log_intake_event(event_type, ...)`         | Log intake activity    |
| `ops.register_heartbeat(worker_id, ...)`        | Worker health ping     |

### intake Schema

| RPC                                       | Purpose                  |
| ----------------------------------------- | ------------------------ |
| `intake.create_foil_dataset(...)`         | Create dataset record    |
| `intake.update_foil_dataset_mapping(...)` | Store column mapping     |
| `intake.update_foil_dataset_status(...)`  | Update processing status |
| `intake.finalize_foil_dataset(...)`       | Set final counts         |
| `intake.store_foil_raw_rows_bulk(...)`    | Bulk insert raw rows     |
| `intake.update_foil_raw_row_status(...)`  | Mark row processed       |
| `intake.quarantine_foil_row(...)`         | Quarantine bad row       |

### public Schema

| RPC                                 | Purpose                                  |
| ----------------------------------- | ---------------------------------------- |
| `ops.upsert_judgment(...)`          | Insert/update judgment                   |
| `ops.upsert_judgment_extended(...)` | Extended judgment upsert with all fields |

## RPCClient Usage

The `backend/workers/rpc_client.py` module provides type-safe Python wrappers:

```python
from backend.workers.rpc_client import RPCClient

# Get connection from pool
with get_connection() as conn:
    rpc = RPCClient(conn)

    # Create dataset
    dataset_id = rpc.create_foil_dataset(
        file_name="import.csv",
        source_system="simplicity",
        uploaded_by="worker-123"
    )

    # Store raw rows
    rpc.store_foil_raw_rows_bulk(
        dataset_id=dataset_id,
        rows=[{"col1": "val1", ...}, ...]
    )

    # Upsert judgment
    rpc.upsert_judgment_extended(
        case_number="2024-CV-001",
        debtor_name="John Doe",
        principal_amount=Decimal("10000.00"),
        ...
    )

    # Commit at worker loop level
    conn.commit()
```

## Transaction Boundaries

**Critical**: RPCClient methods do NOT commit internally. The worker loop controls transactions:

```python
def process_job(job):
    with get_connection() as conn:
        rpc = RPCClient(conn)
        try:
            # All RPC calls happen in one transaction
            rpc.update_job_status(job.id, "processing")
            result = do_work(rpc, job.payload)
            rpc.update_job_status(job.id, "completed", result=result)
            conn.commit()  # Single commit for entire job
        except Exception as e:
            conn.rollback()  # Atomically undo all changes
            rpc.update_job_status(job.id, "failed", error=str(e))
            conn.commit()
```

## Guard Tests

The test suite includes guards that fail if raw SQL writes are detected:

- `tests/test_raw_sql_guard.py` - AST-based scanner for cur.execute() with INSERT/UPDATE/DELETE
- Runs on every PR via pytest
- Covers all files in `backend/workers/`
- Excludes `rpc_client.py` (which is supposed to contain SQL)

To run manually:

```bash
python -m pytest tests/test_raw_sql_guard.py -v
```

## Migration Path

To add a new protected operation:

1. **Create the RPC** in a new migration:

   ```sql
   CREATE OR REPLACE FUNCTION ops.my_new_operation(...)
   RETURNS ... AS $$
   BEGIN
       -- implementation
   END;
   $$ LANGUAGE plpgsql SECURITY DEFINER;

   GRANT EXECUTE ON FUNCTION ops.my_new_operation(...) TO dragonfly_app;
   ```

2. **Add RPCClient method** in `backend/workers/rpc_client.py`:

   ```python
   def my_new_operation(self, param1: str, ...) -> ReturnType:
       """Docstring explaining the operation."""
       with self.conn.cursor() as cur:
           cur.execute("SELECT ops.my_new_operation(%s, ...)", [param1, ...])
           return cur.fetchone()[0]
   ```

3. **Update guard test** if needed (new protected table)

4. **Apply migration**: `python -m tools.db_push --env dev`

5. **Verify**: `python -m pytest tests/test_raw_sql_guard.py -v`

## Related Files

- [rpc_client.py](../backend/workers/rpc_client.py) - RPCClient implementation
- [20251230000000_world_class_security.sql](../supabase/migrations/20251230000000_world_class_security.sql) - Initial security lockdown
- [20251231000000_intake_schema_rpcs.sql](../supabase/migrations/20251231000000_intake_schema_rpcs.sql) - Intake schema RPCs
- [test_raw_sql_guard.py](../tests/test_raw_sql_guard.py) - Guard tests
