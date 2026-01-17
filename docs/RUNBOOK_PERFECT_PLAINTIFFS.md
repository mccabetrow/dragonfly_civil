# Perfect Plaintiffs Engine: Operator Runbook

**Author:** CEO / Principal Engineer  
**Date:** January 2026  
**Version:** 1.0.0

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Worker: ny_judgments_pilot](#worker-ny_judgments_pilot)
3. [Worker: plaintiff_targeting](#worker-plaintiff_targeting)
4. [Cron Schedule](#cron-schedule)
5. [Monitoring & Alerts](#monitoring--alerts)
6. [Verification Queries](#verification-queries)
7. [Troubleshooting](#troubleshooting)
8. [Rollback Procedures](#rollback-procedures)

---

## System Overview

The Perfect Plaintiffs Engine consists of two workers:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PERFECT PLAINTIFFS ENGINE                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐     │
│  │   Court Portal  │─────▶│ ny_judgments_   │─────▶│  judgments_raw  │     │
│  │   (WebCivil)    │      │ pilot worker    │      │  (Landing Zone) │     │
│  └─────────────────┘      └─────────────────┘      └─────────────────┘     │
│                                                            │                │
│                                                            ▼                │
│                           ┌─────────────────┐      ┌─────────────────┐     │
│                           │ plaintiff_      │─────▶│ plaintiff_leads │     │
│                           │ targeting       │      │ (Scored Queue)  │     │
│                           └─────────────────┘      └─────────────────┘     │
│                                                            │                │
│                                                            ▼                │
│                                                    ┌─────────────────┐     │
│                                                    │   Outreach      │     │
│                                                    │   (Manual/Auto) │     │
│                                                    └─────────────────┘     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Tables

| Table                    | Purpose                   | Write By            | Read By             |
| ------------------------ | ------------------------- | ------------------- | ------------------- |
| `public.ingest_runs`     | Worker execution audit    | ny_judgments_pilot  | Operators           |
| `public.judgments_raw`   | Raw judgment landing zone | ny_judgments_pilot  | plaintiff_targeting |
| `public.targeting_runs`  | Targeting execution audit | plaintiff_targeting | Operators           |
| `public.plaintiff_leads` | Scored, prioritized leads | plaintiff_targeting | Outreach team       |

### Exit Codes

| Code | Meaning                 | Action                     |
| ---- | ----------------------- | -------------------------- |
| 0    | Success                 | None                       |
| 1    | Recoverable failure     | Retry                      |
| 2    | Configuration error     | Fix config, manual restart |
| 3    | Scraper not implemented | Expected (development)     |
| 4    | Database unreachable    | Check connectivity         |

---

## Worker: ny_judgments_pilot

### Purpose

Fetches civil judgments from NY court portal and lands them in `judgments_raw`.

### Location

```
workers/ny_judgments_pilot/
├── __init__.py
├── __main__.py
├── config.py
├── db.py
├── main.py
├── normalize.py
├── scraper.py      # STUB - awaiting portal confirmation
└── README.md
```

### Running Locally

```powershell
# Set environment
$env:SUPABASE_MODE = "dev"
$env:DATABASE_URL = "postgresql://..."  # Get from load_env.ps1

# Run worker
.\.venv\Scripts\python.exe -m workers.ny_judgments_pilot
```

### Environment Variables

| Variable             | Required | Default        | Description                    |
| -------------------- | -------- | -------------- | ------------------------------ |
| `DATABASE_URL`       | Yes      | -              | Postgres connection string     |
| `ENV`                | No       | dev            | Environment (dev/staging/prod) |
| `NY_PILOT_COUNTY`    | No       | kings          | County to scrape               |
| `NY_PILOT_CASE_TYPE` | No       | money_judgment | Case type filter               |

### Expected Output

```
2026-01-14T10:00:00Z level=INFO worker_start worker=ny_judgments_pilot version=1.0.0
2026-01-14T10:00:00Z level=INFO batch_id_generated source_batch_id=ny_judgments_2026-01-14
2026-01-14T10:00:00Z level=INFO db_connected application_name=ny_judgments_pilot
2026-01-14T10:00:01Z level=INFO import_run_created run_id=abc-123-...
2026-01-14T10:00:01Z level=WARNING scraper_not_implemented message='Target Portal...'
2026-01-14T10:00:01Z level=INFO worker_shutdown
```

**Note:** Exit code 3 is expected until scraper is implemented.

### Current Status

- ✅ Infrastructure complete
- ✅ Database operations implemented
- ✅ Normalization logic implemented
- ⏳ **Scraper is STUB** - awaiting:
  1. Portal access credentials
  2. API documentation
  3. Legal review for automated access

---

## Worker: plaintiff_targeting

### Purpose

Transforms `judgments_raw` into scored, prioritized `plaintiff_leads`.

### Location

```
workers/plaintiff_targeting/
├── __init__.py
├── __main__.py
└── main.py
```

### Running Locally

```powershell
# Set environment
$env:SUPABASE_MODE = "dev"
$env:DATABASE_URL = "postgresql://..."

# Run worker
.\.venv\Scripts\python.exe -m workers.plaintiff_targeting
```

### Environment Variables

| Variable               | Required | Default | Description                |
| ---------------------- | -------- | ------- | -------------------------- |
| `DATABASE_URL`         | Yes      | -       | Postgres connection string |
| `ENV`                  | No       | dev     | Environment                |
| `TARGETING_BATCH_SIZE` | No       | 100     | Records per batch          |
| `TARGETING_MIN_SCORE`  | No       | 20      | Minimum score threshold    |
| `TARGETING_COUNTY`     | No       | None    | Filter by county           |
| `TARGETING_SOURCE`     | No       | None    | Filter by source system    |

### Expected Output

```
2026-01-14T11:00:00Z level=INFO worker_start worker=plaintiff_targeting version=1.0.0
2026-01-14T11:00:00Z level=INFO db_connected application_name=plaintiff_targeting
2026-01-14T11:00:00Z level=INFO targeting_run_created run_id=xyz-456-...
2026-01-14T11:00:00Z level=INFO judgments_fetched count=250
2026-01-14T11:00:05Z level=INFO progress evaluated=100 created=85 updated=0 skipped=15
2026-01-14T11:00:10Z level=INFO progress evaluated=200 created=170 updated=0 skipped=30
2026-01-14T11:00:12Z level=INFO worker_complete run_id=xyz-456-... evaluated=250 created=212 updated=0 skipped=38
```

---

## Cron Schedule

### Railway Cron Configuration

```yaml
# railway.toml (or Railway dashboard)
[service]
name = "ny-judgments-worker"

[cron]
schedule = "0 6 * * *"  # Daily at 6 AM UTC
command = "python -m workers.ny_judgments_pilot"
```

```yaml
[service]
name = "plaintiff-targeting-worker"

[cron]
schedule = "0 7 * * *"  # Daily at 7 AM UTC (after ingestion)
command = "python -m workers.plaintiff_targeting"
```

### Recommended Schedule

| Worker              | Schedule          | Reasoning                                  |
| ------------------- | ----------------- | ------------------------------------------ |
| ny_judgments_pilot  | 6:00 AM UTC daily | Before business hours, after court updates |
| plaintiff_targeting | 7:00 AM UTC daily | After ingestion completes                  |

---

## Monitoring & Alerts

### Key Metrics

| Metric                               | Normal   | Warning     | Critical           |
| ------------------------------------ | -------- | ----------- | ------------------ |
| `ingest_runs.status = 'completed'`   | Last 24h | Missing 24h | Missing 48h        |
| `records_inserted / records_fetched` | >90%     | <90%        | <50%               |
| Exit code 3 (scraper stub)           | Expected | -           | Unexpected in prod |
| Exit code 4 (DB unreachable)         | Never    | Any         | Multiple           |

### Alert Queries

```sql
-- Check last successful ingest run
SELECT
    id, started_at, status, records_fetched, records_inserted
FROM public.ingest_runs
WHERE worker_name = 'ny_judgments_pilot'
  AND status = 'completed'
ORDER BY started_at DESC
LIMIT 1;

-- Alert if no successful run in 48 hours
SELECT
    CASE
        WHEN MAX(started_at) < NOW() - INTERVAL '48 hours' THEN 'CRITICAL'
        WHEN MAX(started_at) < NOW() - INTERVAL '24 hours' THEN 'WARNING'
        ELSE 'OK'
    END as alert_level
FROM public.ingest_runs
WHERE worker_name = 'ny_judgments_pilot'
  AND status = 'completed';
```

---

## Verification Queries

### Daily Health Check

```sql
-- 1. Ingest run status (last 7 days)
SELECT
    DATE(started_at) as run_date,
    status,
    records_fetched,
    records_inserted,
    records_skipped,
    duration_ms
FROM public.ingest_runs
WHERE worker_name = 'ny_judgments_pilot'
  AND started_at > NOW() - INTERVAL '7 days'
ORDER BY started_at DESC;

-- 2. Targeting run status (last 7 days)
SELECT
    DATE(started_at) as run_date,
    status,
    judgments_evaluated,
    leads_created,
    leads_updated,
    leads_skipped,
    duration_ms
FROM public.targeting_runs
WHERE started_at > NOW() - INTERVAL '7 days'
ORDER BY started_at DESC;

-- 3. Lead pipeline summary
SELECT * FROM public.v_plaintiff_leads_dashboard;

-- 4. Top pending leads
SELECT * FROM public.v_plaintiff_leads_queue LIMIT 20;
```

### Data Quality Checks

```sql
-- Check for orphaned judgments (no lead created)
SELECT COUNT(*) as orphaned_judgments
FROM public.judgments_raw jr
LEFT JOIN public.plaintiff_leads pl ON pl.source_judgment_id = jr.id
WHERE pl.id IS NULL
  AND jr.status = 'pending';

-- Check score distribution
SELECT
    priority_tier,
    COUNT(*) as count,
    ROUND(AVG(collectability_score), 1) as avg_score,
    ROUND(AVG(judgment_amount)::numeric, 2) as avg_amount
FROM public.plaintiff_leads
GROUP BY priority_tier
ORDER BY 1;

-- Check for data completeness
SELECT
    COUNT(*) as total_leads,
    COUNT(*) FILTER (WHERE plaintiff_phone IS NOT NULL) as has_phone,
    COUNT(*) FILTER (WHERE plaintiff_email IS NOT NULL) as has_email,
    COUNT(*) FILTER (WHERE debtor_address IS NOT NULL) as has_address,
    COUNT(*) FILTER (WHERE judgment_amount IS NOT NULL) as has_amount
FROM public.plaintiff_leads;
```

### Reconciliation

```sql
-- Compare ingest_runs vs judgments_raw counts
SELECT
    ir.id as run_id,
    ir.started_at,
    ir.records_inserted as reported_inserted,
    COUNT(jr.id) as actual_rows,
    ir.records_inserted - COUNT(jr.id) as discrepancy
FROM public.ingest_runs ir
LEFT JOIN public.judgments_raw jr ON jr.ingest_run_id = ir.id
WHERE ir.started_at > NOW() - INTERVAL '7 days'
GROUP BY ir.id, ir.started_at, ir.records_inserted
HAVING ir.records_inserted != COUNT(jr.id)
ORDER BY ir.started_at DESC;

-- Compare targeting_runs vs plaintiff_leads counts
SELECT
    tr.id as run_id,
    tr.started_at,
    tr.leads_created as reported_created,
    COUNT(pl.id) as actual_leads,
    tr.leads_created - COUNT(pl.id) as discrepancy
FROM public.targeting_runs tr
LEFT JOIN public.plaintiff_leads pl ON pl.targeting_run_id = tr.id
WHERE tr.started_at > NOW() - INTERVAL '7 days'
GROUP BY tr.id, tr.started_at, tr.leads_created
HAVING tr.leads_created != COUNT(pl.id)
ORDER BY tr.started_at DESC;
```

---

## Troubleshooting

### Exit Code 2: Configuration Error

**Symptoms:**

```
FATAL config_error=DATABASE_URL environment variable is required
```

**Resolution:**

1. Verify environment variables are set
2. Check Railway/environment configuration
3. Run `./scripts/load_env.ps1` locally

### Exit Code 3: Scraper Not Implemented

**Symptoms:**

```
level=WARNING scraper_not_implemented message='Target Portal (NY WebCivil) scraping not implemented...'
```

**Resolution:**

- This is expected during development
- Scraper implementation blocked on portal confirmation
- No action needed until scraper is complete

### Exit Code 4: Database Unreachable

**Symptoms:**

```
level=CRITICAL db_connection_failed error=connection refused
```

**Resolution:**

1. Check Supabase dashboard for outages
2. Verify DATABASE_URL format (pooler vs direct)
3. Run `python -m tools.probe_db` to diagnose

### High Skip Rate in Targeting

**Symptoms:**

```
worker_complete ... skipped=500 created=50
```

**Causes:**

- Judgments missing plaintiff/debtor names
- Scores below threshold (default 20)
- Already processed judgments

**Investigation:**

```sql
-- Check why judgments are being skipped
SELECT
    CASE
        WHEN raw_payload->>'plaintiff' IS NULL AND raw_payload->>'debtor' IS NULL
             THEN 'missing_parties'
        WHEN pl.id IS NOT NULL THEN 'already_targeted'
        ELSE 'unknown'
    END as skip_reason,
    COUNT(*)
FROM public.judgments_raw jr
LEFT JOIN public.plaintiff_leads pl ON pl.source_judgment_id = jr.id
GROUP BY 1;
```

### Zero Records Fetched

**Symptoms:**

```
judgments_fetched count=0
```

**Causes:**

- Scraper returning empty results
- Date range has no new judgments
- All judgments already processed

**Investigation:**

```sql
-- Check last judgment captured
SELECT MAX(captured_at), COUNT(*)
FROM public.judgments_raw;

-- Check judgment status distribution
SELECT status, COUNT(*)
FROM public.judgments_raw
GROUP BY status;
```

---

## Rollback Procedures

### Rollback a Bad Ingest Run

If bad data was ingested, mark the run and its records as invalid:

```sql
-- 1. Mark ingest run as failed
UPDATE public.ingest_runs
SET
    status = 'failed',
    error_message = 'Manually rolled back: [REASON]'
WHERE id = 'RUN-ID-HERE';

-- 2. Mark judgments from that run as skipped
UPDATE public.judgments_raw
SET
    status = 'skipped',
    error_code = 'ROLLBACK',
    error_message = 'Manually rolled back: [REASON]'
WHERE ingest_run_id = 'RUN-ID-HERE';

-- 3. Delete any leads created from those judgments
DELETE FROM public.plaintiff_leads
WHERE source_judgment_id IN (
    SELECT id FROM public.judgments_raw
    WHERE ingest_run_id = 'RUN-ID-HERE'
);
```

### Rollback a Bad Targeting Run

```sql
-- 1. Mark targeting run as failed
UPDATE public.targeting_runs
SET
    status = 'failed',
    error_message = 'Manually rolled back: [REASON]'
WHERE id = 'RUN-ID-HERE';

-- 2. Delete leads from that run
DELETE FROM public.plaintiff_leads
WHERE targeting_run_id = 'RUN-ID-HERE';
```

### Re-run After Rollback

After rollback, the workers can be re-run:

- ny_judgments_pilot will skip already-processed batches (same date)
- plaintiff_targeting will re-process orphaned judgments

---

## Appendix: Collectability Score Quick Reference

| Tier         | Score  | Volume Target | Outreach SLA  |
| ------------ | ------ | ------------- | ------------- |
| A (Platinum) | 80-100 | Top 10%       | Same day      |
| B (Gold)     | 60-79  | Next 20%      | 48 hours      |
| C (Silver)   | 40-59  | Next 30%      | 1 week        |
| D (Bronze)   | 20-39  | Next 30%      | Batch         |
| F (Skip)     | 0-19   | Bottom 10%    | Do not pursue |

---

_For detailed scoring logic, see [docs/COLLECTABILITY_SCORING_SPEC.md](COLLECTABILITY_SCORING_SPEC.md)_
