# NY Judgments Pilot Worker

Scheduled ingestion worker for NY civil judgment data. Runs on Railway cron, fetches from source, deduplicates, and lands records in `judgments_raw` for downstream processing.

## Quick Reference

| Item              | Value                                                                                    |
| ----------------- | ---------------------------------------------------------------------------------------- |
| **Run Command**   | `python -m workers.ny_judgments_pilot`                                                   |
| **Required Vars** | `DATABASE_URL`, `ENV`, `SOURCE_SYSTEM`, `PILOT_COUNTY`, `PILOT_COURT`, `PILOT_CASE_TYPE` |
| **Exit Codes**    | `0`=success, `1`=partial, `2`=config, `3`=db, `4`=source                                 |

> **⚠️ STRICT POLICY**: This worker uses `DATABASE_URL` and `ENV` only.
> It does NOT fall back to `SUPABASE_DB_URL` or `ENVIRONMENT`.
> Deployment must explicitly map these variables.

---

## Purpose

This worker is the **first stage** of the judgment ingestion pipeline. It:

1. Fetches raw judgment records from NY eCourts (or configured source)
2. Normalizes and deduplicates using SHA-256 hashing
3. Lands records in `judgments_raw` (append-only staging table)
4. Logs execution metrics to `ingest_runs` for observability

**It does NOT:**

- Parse or extract structured data (that's the parser worker)
- Write to `judgments` (that's the promotion worker)
- Run continuously (it's a batch worker that exits)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           RAILWAY CRON TRIGGER                               │
│                         (every 6 hours or manual)                            │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              main.py                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   config    │  │   scraper   │  │  normalize  │  │     db      │         │
│  │   .py       │──│   .py       │──│   .py       │──│   .py       │         │
│  │             │  │             │  │             │  │             │         │
│  │ Load env    │  │ Fetch from  │  │ Canonicalize│  │ Upsert to   │         │
│  │ Validate    │  │ source      │  │ Dedupe hash │  │ Postgres    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SUPABASE POSTGRES                                    │
│  ┌───────────────────────────┐  ┌───────────────────────────────────────┐   │
│  │      ingest_runs          │  │           judgments_raw               │   │
│  │  (audit log of runs)      │  │  (landing zone, append-only)          │   │
│  │                           │  │                                       │   │
│  │  - run_id                 │  │  - dedupe_key (UNIQUE)                │   │
│  │  - status                 │  │  - content_hash                       │   │
│  │  - records_fetched        │  │  - raw_payload (JSONB)                │   │
│  │  - records_inserted       │  │  - status: pending/processed/failed   │   │
│  └───────────────────────────┘  └───────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

```
Source API          Worker                  Database
    │                  │                       │
    │   GET /search    │                       │
    │◄─────────────────│                       │
    │                  │                       │
    │   JSON records   │                       │
    │─────────────────►│                       │
    │                  │                       │
    │                  │  normalize()          │
    │                  │  compute dedupe_key   │
    │                  │  compute content_hash │
    │                  │                       │
    │                  │  INSERT ... ON        │
    │                  │  CONFLICT DO NOTHING  │
    │                  │──────────────────────►│
    │                  │                       │
    │                  │  rowcount (inserted)  │
    │                  │◄──────────────────────│
    │                  │                       │
```

---

## Local Development

### Prerequisites

```powershell
# From repo root
.\.venv\Scripts\Activate.ps1
pip install psycopg[binary] httpx
```

### Environment Setup

Create `.env.local` or export directly:

```bash
# Required
export ENV=dev
export DATABASE_URL="<your-supabase-connection-string>"
export SOURCE_SYSTEM="ny_ecourts"
export PILOT_COUNTY="kings"
export PILOT_COURT="civil"
export PILOT_CASE_TYPE="money_judgment"

# Optional (with defaults)
export PILOT_RANGE_MONTHS=6
export DELTA_LOOKBACK_DAYS=3
export LOG_LEVEL=INFO
```

### Running Locally

```powershell
# Canonical entrypoint (the ONLY supported way to run)
python -m workers.ny_judgments_pilot

# With explicit env vars
$env:ENV="dev"
$env:DATABASE_URL="<your-supabase-connection-string>"
$env:SOURCE_SYSTEM="ny_ecourts"
$env:PILOT_COUNTY="kings"
$env:PILOT_COURT="civil"
$env:PILOT_CASE_TYPE="money_judgment"
python -m workers.ny_judgments_pilot
```

> **Note**: Do NOT use `python -m workers.ny_judgments_pilot.main`.
> The canonical entrypoint is `python -m workers.ny_judgments_pilot`.

### Verifying Results

```sql
-- Check ingest_runs
SELECT id, status, records_fetched, records_inserted, records_skipped
FROM ingest_runs
WHERE worker_name = 'ny_judgments_pilot'
ORDER BY started_at DESC
LIMIT 5;

-- Check landed records
SELECT COUNT(*), status
FROM judgments_raw
WHERE source_system = 'ny_ecourts'
GROUP BY status;
```

---

## Required Environment Variables

> **⚠️ STRICT NAMING POLICY**
>
> This worker uses **`DATABASE_URL`** and **`ENV`** exclusively.
> It does NOT fall back to `SUPABASE_DB_URL`, `ENVIRONMENT`, or any other aliases.
> This ensures service decoupling - each service explicitly declares its dependencies.

| Variable              | Required | Default | Description                                       |
| --------------------- | -------- | ------- | ------------------------------------------------- |
| `DATABASE_URL`        | ✅       | -       | PostgreSQL connection string (direct, not pooled) |
| `ENV`                 | ❌       | `dev`   | Environment: `dev`, `staging`, `prod`             |
| `SOURCE_SYSTEM`       | ✅       | -       | Source identifier (e.g., `ny_ecourts`)            |
| `PILOT_COUNTY`        | ✅       | -       | County filter (e.g., `kings`, `queens`)           |
| `PILOT_COURT`         | ✅       | -       | Court filter (e.g., `civil`, `small_claims`)      |
| `PILOT_CASE_TYPE`     | ✅       | -       | Case type filter (e.g., `money_judgment`)         |
| `PILOT_RANGE_MONTHS`  | ❌       | `6`     | Initial backfill range in months                  |
| `DELTA_LOOKBACK_DAYS` | ❌       | `3`     | Overlap days for delta runs                       |
| `LOG_LEVEL`           | ❌       | `INFO`  | Logging level                                     |

### Railway Variable Mapping

In Railway, map the shared Supabase variable explicitly:

```
DATABASE_URL=${{shared.SUPABASE_DB_URL}}
ENV=prod
```

This explicit mapping ensures the worker doesn't accidentally inherit API service variables.

---

## Railway Deployment

### Cron Configuration

In `railway.toml` or Railway dashboard:

```toml
[service]
name = "ny-judgments-pilot"

[deploy]
startCommand = "python -m workers.ny_judgments_pilot"  # Canonical entrypoint
restartPolicyType = "never"  # Worker exits, don't restart

[cron]
schedule = "0 */6 * * *"  # Every 6 hours
```

### Environment Variables

Set in Railway dashboard under **Variables**:

```
ENV=prod
DATABASE_URL=${{Supabase.DATABASE_URL}}
SOURCE_SYSTEM=ny_ecourts
PILOT_COUNTY=kings
PILOT_COURT=civil
PILOT_CASE_TYPE=money_judgment
LOG_LEVEL=INFO
```

### Monitoring

- **Logs**: Railway dashboard → Service → Logs
- **Metrics**: Check `ingest_runs` table for run history
- **Alerts**: Configure Railway webhook on non-zero exit

---

## Exit Codes

| Code | Status       | Meaning                    | Action                              |
| ---- | ------------ | -------------------------- | ----------------------------------- |
| `0`  | Success      | All records processed      | None                                |
| `1`  | Partial      | Some records failed        | Check `ingest_runs.error_details`   |
| `2`  | Config Error | Missing/invalid env vars   | Fix configuration                   |
| `3`  | DB Error     | Connection or query failed | Check DATABASE_URL, Supabase status |
| `4`  | Source Error | Scraper failed             | Check source API, rate limits       |

---

## Failure Modes

### Transient Failures

| Failure                   | Behavior                        | Recovery                  |
| ------------------------- | ------------------------------- | ------------------------- |
| Source API timeout        | Retry with backoff (3 attempts) | Automatic                 |
| Rate limit (429)          | Exponential backoff             | Automatic                 |
| Single record parse error | Skip record, continue           | Logged in `error_details` |
| Batch insert partial fail | Commit successful, log failed   | Manual review             |

### Fatal Failures

| Failure                    | Exit Code | Recovery                   |
| -------------------------- | --------- | -------------------------- |
| DATABASE_URL invalid       | 2         | Fix env var                |
| Cannot connect to Postgres | 3         | Check network, credentials |
| Source API auth failure    | 4         | Refresh API credentials    |
| Ingest run creation fails  | 3         | Check `ingest_runs` schema |

### Idempotency Guarantee

The worker is **safe to re-run** at any time:

- `dedupe_key` UNIQUE constraint prevents duplicates
- `ON CONFLICT DO NOTHING` makes inserts idempotent
- Delta window overlaps ensure no gaps

---

## Extending to New Counties/Case Types

### Adding a New County

1. **No code changes required** - just change env vars:

```bash
export PILOT_COUNTY="queens"  # Was "kings"
```

2. Deploy as a separate Railway service or update existing.

### Adding a New Case Type

1. Update `PILOT_CASE_TYPE`:

```bash
export PILOT_CASE_TYPE="consumer_credit"
```

2. Verify the source API supports this case type filter.

### Running Multiple Configurations

Deploy separate Railway services with different env vars:

```
ny-judgments-kings-civil     → PILOT_COUNTY=kings, PILOT_CASE_TYPE=money_judgment
ny-judgments-queens-civil    → PILOT_COUNTY=queens, PILOT_CASE_TYPE=money_judgment
ny-judgments-kings-consumer  → PILOT_COUNTY=kings, PILOT_CASE_TYPE=consumer_credit
```

All land in the same `judgments_raw` table, differentiated by `source_county` and `case_type` columns.

### Adding a New Source System

1. Create new scraper module: `workers/nj_judgments_pilot/scraper.py`
2. Implement `fetch_judgments()` with same interface
3. Reuse `normalize.py` and `db.py` (they're source-agnostic)
4. Set `SOURCE_SYSTEM=nj_ecourts` in env

---

## File Structure

```
workers/ny_judgments_pilot/
├── __init__.py      # Package marker
├── config.py        # Environment loading, validation
├── scraper.py       # Source API interaction (fetch only)
├── normalize.py     # Canonicalization, hashing (pure functions)
├── db.py            # All database operations (psycopg3)
├── main.py          # Orchestration (no business logic)
└── README.md        # This file
```

---

## Observability

### Structured Logs

All log entries include structured `extra` fields:

```
2026-01-13T10:30:00+0000 | INFO     | workers.ny_judgments_pilot.main | [START] NY Judgments Pilot Worker
2026-01-13T10:30:01+0000 | INFO     | workers.ny_judgments_pilot.db | [DB] Ingest run created | ingest_run_id=abc-123
2026-01-13T10:30:05+0000 | INFO     | workers.ny_judgments_pilot.main | [FETCH] Complete | fetched=150
2026-01-13T10:30:06+0000 | INFO     | workers.ny_judgments_pilot.main | [INSERT] Complete | inserted=148, skipped=2
2026-01-13T10:30:06+0000 | INFO     | workers.ny_judgments_pilot.main | [SUMMARY] Worker complete | status=completed
```

### Key Metrics

Query from `ingest_runs`:

```sql
-- Last 7 days summary
SELECT
    DATE(started_at) AS run_date,
    COUNT(*) AS runs,
    SUM(records_fetched) AS total_fetched,
    SUM(records_inserted) AS total_inserted,
    SUM(records_skipped) AS total_duplicates,
    SUM(records_errored) AS total_errors
FROM ingest_runs
WHERE worker_name = 'ny_judgments_pilot'
  AND started_at > NOW() - INTERVAL '7 days'
GROUP BY DATE(started_at)
ORDER BY run_date DESC;
```

---

## Troubleshooting

### "Config validation failed"

Check all required env vars are set. Run with `LOG_LEVEL=DEBUG` for details.

### "Database connection failed"

1. Verify `DATABASE_URL` uses the Postgres connection string format
2. Check Supabase dashboard for connection limits
3. Ensure IP is allowlisted (Railway IPs may need adding)

### "Scraper returned 0 records"

1. Check date window in logs (`[WINDOW]` entries)
2. Verify source API is responding
3. Check if filters (county, court, case_type) match available data

### High duplicate rate

Expected behavior for overlapping delta windows. If >90% duplicates:

1. Increase `DELTA_LOOKBACK_DAYS` if seeing gaps
2. Decrease if too much overlap

---

## Related Documentation

- [Dragonfly Codex Guide](../../Dragonfly_Codex_Guide.md) - System architecture
- [Database Schema](../../supabase/migrations/) - Table definitions
- [Backend Workers](../../backend/workers/) - Other worker patterns

---

## Changelog

| Date       | Change                                        |
| ---------- | --------------------------------------------- |
| 2026-01-13 | Initial implementation for Kings County pilot |
