# SRE Sentinel - Pipeline Health Monitoring Guide

**Status**: ✅ Deployed to Dev  
**Created**: 2025-01-04  
**Author**: Dragonfly SRE Team

---

## Overview

The **Sentinel** is an automated health monitoring system for the Dragonfly ingestion engine. It provides deep visibility into batch processing performance, error patterns, and PostgREST schema cache issues.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Supabase PostgreSQL                      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  ops.v_batch_performance                             │   │
│  │  ops.v_error_distribution                            │   │
│  │  ops.v_pipeline_health                               │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │
                    [PostgREST API]
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              backend/workers/sentinel.py                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Check 1: Stuck Batches (> 10 min)         [CRITICAL]│   │
│  │  Check 2: Error Spikes (> 15%)              [WARNING]│   │
│  │  Check 3: Schema Cache (PGRST002)          [CRITICAL]│   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ JSON Output   │ → Log Aggregator / Alerting
                    │ Exit Code     │ → Cron Job / Systemd
                    │ Discord Hook  │ → (Future)
                    └───────────────┘
```

---

## SQL Views (ops schema)

### 1. `ops.v_batch_performance`

**Purpose**: Hourly rollup of ingestion performance metrics

**Columns**:

- `hour_bucket` - Hour timestamp (date_trunc)
- `total_batches` - Batches in this hour
- `completed_batches` / `failed_batches` - Status breakdown
- `avg_parse_ms` / `avg_db_ms` / `avg_total_ms` - Timing metrics
- `total_rows` / `inserted_rows` / `skipped_rows` / `error_rows` - Row counts
- `dedupe_rate_pct` - Percentage of rows skipped (duplicates)
- `error_rate_pct` - Percentage of rows with errors

**Usage**:

```sql
-- Last 24 hours of batch performance
SELECT * FROM ops.v_batch_performance
ORDER BY hour_bucket DESC
LIMIT 24;

-- Today's throughput summary
SELECT
    hour_bucket::time AS hour,
    total_batches,
    total_rows,
    ROUND(total_rows::numeric / NULLIF(total_batches, 0), 0) AS avg_rows_per_batch,
    error_rate_pct
FROM ops.v_batch_performance
WHERE hour_bucket >= CURRENT_DATE
ORDER BY hour_bucket;
```

**Dashboard Integration**:

```typescript
// dragonfly-dashboard/src/lib/api.ts
export async function getBatchPerformance(hours: number = 24) {
  const { data } = await supabase
    .schema("ops")
    .from("v_batch_performance")
    .select("*")
    .order("hour_bucket", { ascending: false })
    .limit(hours);
  return data;
}
```

---

### 2. `ops.v_error_distribution`

**Purpose**: Top error codes by frequency across all batches

**Columns**:

- `error_code` - Error code from intake.row_errors
- `occurrence_count` - Total occurrences
- `affected_batches` - Distinct batches with this error
- `sample_message` - Example error message
- `last_seen_at` - Most recent occurrence

**Usage**:

```sql
-- Top 10 errors in last 7 days
SELECT
    error_code,
    occurrence_count,
    affected_batches,
    sample_message,
    last_seen_at
FROM ops.v_error_distribution
ORDER BY occurrence_count DESC
LIMIT 10;
```

**Use Case**: Identify systemic validation issues (e.g., missing required fields, date format errors)

---

### 3. `ops.v_pipeline_health`

**Purpose**: Real-time snapshot of pipeline state with age tracking

**Columns**:

- `status` - Batch status (uploaded, processing, validating, etc.)
- `batch_count` - Number of batches in this state
- `oldest_batch_at` - Timestamp of oldest batch
- `oldest_age_minutes` - Age in minutes
- `newest_batch_at` - Most recent batch

**Usage**:

```sql
-- Find stuck batches (processing > 10 minutes)
SELECT
    status,
    batch_count,
    oldest_batch_at,
    oldest_age_minutes
FROM ops.v_pipeline_health
WHERE status IN ('processing', 'validating', 'inserting')
  AND oldest_age_minutes > 10;
```

**Use Case**: Sentinel's primary check for detecting stuck pipelines

---

## Sentinel Health Checks

### Check 1: Stuck Batches 🔴 CRITICAL

**Logic**:

```python
# Query ops.v_pipeline_health
# If any batch is in processing states for > 10 minutes → CRITICAL alert
```

**Alert Example**:

```json
{
  "check": "stuck_batches",
  "level": "critical",
  "message": "3 batches stuck > 10m: processing(2), validating(1)",
  "details": {
    "stuck_batches": [
      { "status": "processing", "batch_count": 2, "oldest_age_minutes": 15.3 },
      { "status": "validating", "batch_count": 1, "oldest_age_minutes": 12.7 }
    ]
  }
}
```

**Remediation**:

1. Check backend logs for exceptions
2. Verify database connectivity
3. Restart worker processes if needed
4. Manually fail stuck batches with rejection reason

---

### Check 2: Error Spikes ⚠️ WARNING

**Logic**:

```python
# Query ops.v_batch_performance (last hour)
# If error_rate_pct > 15% → WARNING alert
```

**Alert Example**:

```json
{
  "check": "error_spike",
  "level": "warning",
  "message": "Error rate 18.5% > 15.0% threshold",
  "details": {
    "error_rate_pct": 18.5,
    "threshold_pct": 15.0,
    "hour_bucket": "2025-01-04T10:00:00",
    "error_rows": 185,
    "total_rows": 1000
  }
}
```

**Remediation**:

1. Query `ops.v_error_distribution` for top error codes
2. Check if bad data batch was uploaded
3. Review validation rules if systemic issue
4. Adjust `error_threshold_percent` if new data source

---

### Check 3: Schema Cache 🔴 CRITICAL

**Logic**:

```python
# Test query to PostgREST
# If PGRST002 detected → Auto-send NOTIFY pgrst, 'reload'
# Log action taken
```

**Alert Example**:

```json
{
  "check": "schema_cache",
  "level": "warning",
  "message": "PGRST002 detected - auto-reload triggered",
  "details": {
    "error": "Could not query the database for the schema cache. Retrying.",
    "action_taken": "NOTIFY pgrst, 'reload'"
  }
}
```

**Remediation**:

- Sentinel auto-reloads schema cache via `NOTIFY pgrst, 'reload'`
- If auto-reload fails → CRITICAL alert (requires manual intervention)
- Check Supabase dashboard for schema locks or migrations in progress

---

## Usage Guide

### One-Time Health Check

```bash
# Dev environment
SUPABASE_MODE=dev python -m backend.workers.sentinel

# Production environment
SUPABASE_MODE=prod python -m backend.workers.sentinel
```

**Output (Human-Readable)**:

```
2025-01-04 10:15:30 | INFO     | sentinel | Running stuck_batches check...
2025-01-04 10:15:31 | INFO     | sentinel | Running error_spike check...
2025-01-04 10:15:32 | INFO     | sentinel | Running schema_cache check...
================================================================================
✅ HEALTH CHECK COMPLETE - Status: HEALTHY
Environment: dev
Timestamp: 2025-01-04T10:15:32.123456Z
================================================================================
✅ No alerts - all systems operational
================================================================================
Metrics: {
  "total_checks": 3,
  "alerts_triggered": 0,
  "critical_alerts": 0,
  "warning_alerts": 0
}
================================================================================
```

**Exit Codes**:

- `0` = Healthy
- `1` = Degraded (warnings)
- `2` = Critical (requires attention)

---

### JSON Output (for Log Aggregators)

```bash
SUPABASE_MODE=prod python -m backend.workers.sentinel --json
```

**Output**:

```json
{
  "timestamp": "2025-01-04T10:15:32.123456Z",
  "environment": "prod",
  "overall_status": "healthy",
  "alerts": [],
  "metrics": {
    "total_checks": 3,
    "alerts_triggered": 0,
    "critical_alerts": 0,
    "warning_alerts": 0
  }
}
```

**Integration with Log Aggregators**:

- Parse JSON output in CloudWatch / Datadog / Splunk
- Alert on `"overall_status": "critical"`
- Track `metrics.critical_alerts` as time series

---

### Continuous Monitoring (Cron / Systemd)

```bash
# Run every 5 minutes
SUPABASE_MODE=prod python -m backend.workers.sentinel --loop --interval 300
```

**Systemd Unit File** (`/etc/systemd/system/dragonfly-sentinel.service`):

```ini
[Unit]
Description=Dragonfly Pipeline Health Monitor (Sentinel)
After=network.target

[Service]
Type=simple
User=dragonfly
WorkingDirectory=/opt/dragonfly
Environment="SUPABASE_MODE=prod"
ExecStart=/opt/dragonfly/.venv/bin/python -m backend.workers.sentinel --loop --interval 300
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Cron Job** (every 5 minutes):

```cron
*/5 * * * * cd /opt/dragonfly && SUPABASE_MODE=prod .venv/bin/python -m backend.workers.sentinel --json >> /var/log/dragonfly/sentinel.log 2>&1
```

---

## Deployment Checklist

### Dev Environment

- [x] Apply migration `20250104_ops_views.sql` to dev
- [x] Test sentinel: `SUPABASE_MODE=dev python -m backend.workers.sentinel --json`
- [x] Verify all 3 checks execute (even if PGRST002 errors occur)
- [x] Fix deprecation warnings (`datetime.utcnow()` → `datetime.now(datetime.UTC)`)

### Prod Environment (When Ready)

- [ ] Apply migration to prod via `DB Push (Prod)` task
- [ ] Test sentinel: `SUPABASE_MODE=prod python -m backend.workers.sentinel`
- [ ] Set up cron job or systemd service for continuous monitoring
- [ ] Configure Discord webhook for CRITICAL alerts (future)
- [ ] Add CloudWatch/Datadog dashboard for JSON metrics

---

## Alerting Roadmap (Future)

### Phase 1: Immediate (Current)

- ✅ Console output with exit codes
- ✅ JSON output for log aggregation
- ✅ Auto-reload schema cache on PGRST002

### Phase 2: Next Sprint

- [ ] Discord webhook integration for CRITICAL alerts
- [ ] Email notifications via SendGrid
- [ ] SMS alerts via Twilio (for production outages)

### Phase 3: Q2 2025

- [ ] Prometheus metrics endpoint
- [ ] Grafana dashboard templates
- [ ] PagerDuty integration

---

## Troubleshooting

### PGRST002 Errors in Dev

**Symptom**: Sentinel reports `"Could not query the database for the schema cache. Retrying."`

**Cause**: Dev database is rate-limited or schema cache is stale

**Resolution**:

1. Wait 30-60 seconds for Supabase to auto-reload
2. Manually reload: `NOTIFY pgrst, 'reload'` (Sentinel does this automatically)
3. Check Supabase dashboard for connection pool usage

### Stuck Batches Not Clearing

**Symptom**: Alert persists even after batch should complete

**Cause**: Worker crashed or database timeout

**Resolution**:

1. Check backend logs: `tail -f /var/log/dragonfly/worker.log`
2. Manually update batch status: `UPDATE intake.simplicity_batches SET status='failed', rejection_reason='Manually failed after timeout' WHERE id='...';`
3. Restart worker: `systemctl restart dragonfly-worker`

### Error Spike False Positives

**Symptom**: 15% threshold too sensitive for new data sources

**Cause**: Different data quality standards per vendor

**Resolution**:

1. Adjust batch-specific threshold: `UPDATE intake.simplicity_batches SET error_threshold_percent=25 WHERE source='vendor_x';`
2. Update Sentinel threshold: Edit `ERROR_SPIKE_THRESHOLD_PCT` in `sentinel.py`
3. Add per-source thresholds (future enhancement)

---

## Metrics & SLOs

| Metric                | Target SLO        | Alert Threshold          |
| --------------------- | ----------------- | ------------------------ |
| Batch Processing Time | < 5 minutes (p95) | > 10 minutes (any batch) |
| Error Rate            | < 5% (hourly)     | > 15% (hourly)           |
| Schema Cache Uptime   | 99.9%             | PGRST002 detected        |
| Dedupe Rate           | 10-30% (normal)   | > 50% (investigate)      |

---

## Files Modified/Created

```
✅ supabase/migrations/20250104_ops_views.sql
   - ops.v_batch_performance (hourly rollup)
   - ops.v_error_distribution (top errors)
   - ops.v_pipeline_health (stuck batch detection)

✅ backend/workers/sentinel.py
   - Stuck batch check (> 10 min)
   - Error spike check (> 15%)
   - Schema cache check (PGRST002 auto-reload)
   - JSON output mode
   - Loop mode for continuous monitoring
```

---

## Next Steps

1. **Deploy to Prod**: Run `DB Push (Prod)` task when dev testing is complete
2. **Set Up Cron**: Add cron job for continuous monitoring
3. **Dashboard**: Build frontend for `ops.v_batch_performance` (Tremor BarChart)
4. **Alerts**: Configure Discord webhook for CRITICAL alerts

---

**End of Guide**
