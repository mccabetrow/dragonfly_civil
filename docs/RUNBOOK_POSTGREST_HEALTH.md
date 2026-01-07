# PostgREST Health & Recovery Runbook

## Overview

This runbook covers health checks and automated recovery for PostgREST PGRST002 errors.

**Problem:** PostgREST schema cache goes stale after database migrations or schema changes, resulting in 503 errors with `PGRST002` error code.

**Solution:** Two-phase approach:

1. **Health Probe** - Strict validation with PGRST002 detection
2. **Recovery Operator** - Automated fix with Discord escalation

---

## Tool 1: Health Probe

**Purpose:** Verify PostgREST health with strict PGRST002 detection in response bodies.

### Usage

```powershell
# Check dev environment
python -m tools.check_postgrest_health --env dev

# Check prod environment
python -m tools.check_postgrest_health --env prod

# Verbose output
python -m tools.check_postgrest_health --env prod --verbose

# JSON output (for CI/CD)
python -m tools.check_postgrest_health --env prod --json
```

### How It Works

1. **Root Check:** `GET /rest/v1/`

   - ✅ 200/401 → PASS (service up)
   - ❌ 503 or body contains "PGRST002" → FAIL

2. **Data Check:** `GET /rest/v1/judgments?select=id&limit=1`
   - ✅ 200/401 → PASS (cache healthy)
   - ❌ Body contains "PGRST002" → FAIL

**Note:** 401 Unauthorized is considered HEALTHY - it means PostgREST is up and enforcing RLS.

### Exit Codes

- `0` - Healthy
- `1` - Unhealthy (PGRST002 detected or connectivity issue)

### Example Output

```
PostgREST Health [PROD]: ✅ HEALTHY
  Root (/)        : ✅ OK (HTTP 401)
  Data (judgments): ✅ OK (HTTP 401)
```

---

## Tool 2: Recovery Operator

**Purpose:** Automated recovery with escalation to human intervention if needed.

### Usage

```powershell
# Recover dev environment
python -m tools.fix_schema_cache --env dev

# Recover prod (with Discord alert on failure)
python -m tools.fix_schema_cache --env prod

# Custom retry settings
python -m tools.fix_schema_cache --env prod --retries 5 --delay 5
```

### Recovery Flow

```
┌─────────────────────────────────────────┐
│ STEP 1: Run Health Probe                │
│ - Strict PGRST002 detection             │
│ - If GREEN → Exit (no action needed)    │
└────────────┬────────────────────────────┘
             │ RED
             ▼
┌─────────────────────────────────────────┐
│ STEP 2: Send NOTIFY pgrst, 'reload'     │
│ - Direct DB connection via psycopg      │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│ STEP 3: Wait 3s and Re-Check            │
│ - Retry up to 3 times (default)         │
│ - If GREEN → Exit SUCCESS               │
└────────────┬────────────────────────────┘
             │ Still RED
             ▼
┌─────────────────────────────────────────┐
│ STEP 4: ESCALATION                      │
│ - Print: "ACTION REQUIRED: Restart..."  │
│ - Send Discord webhook alert            │
│ - Exit 1 (manual intervention needed)   │
└─────────────────────────────────────────┘
```

### Exit Codes

- `0` - Recovery successful or no action needed
- `1` - Recovery failed, manual restart required

### Example Output (Success)

```
======================================================================
  OPERATOR-GRADE SCHEMA CACHE RECOVERY
======================================================================

  Environment: PROD

──────────────────────────────────────────────────────────────────────
  STEP 1: Run Health Probe (Strict PGRST002 Detection)
──────────────────────────────────────────────────────────────────────
  ⚠️  Detected Stale Cache. Attempting NOTIFY reload...

──────────────────────────────────────────────────────────────────────
  STEP 2: Send Schema Reload Command
──────────────────────────────────────────────────────────────────────
  ✅ NOTIFY pgrst sent successfully

──────────────────────────────────────────────────────────────────────
  STEP 3: Wait 3s and Re-Check
──────────────────────────────────────────────────────────────────────
  Attempt 1/3... ✅ Healthy

──────────────────────────────────────────────────────────────────────
  ✅ AUTOMATED RECOVERY SUCCESSFUL
──────────────────────────────────────────────────────────────────────

  PostgREST schema cache has been refreshed.
  PGRST002 errors should now be resolved.
```

### Example Output (Failure → Escalation)

```
──────────────────────────────────────────────────────────────────────
  STEP 3: Wait 3s and Re-Check
──────────────────────────────────────────────────────────────────────
  Attempt 1/3... ⏳ Still unhealthy
  Attempt 2/3... ⏳ Still unhealthy
  Attempt 3/3... ⏳ Still unhealthy

──────────────────────────────────────────────────────────────────────
  ❌ AUTOMATED RECOVERY FAILED
──────────────────────────────────────────────────────────────────────

  🚨 ACTION REQUIRED: Go to Supabase Dashboard → Settings → Restart Project

  Dashboard URL:
    https://supabase.com/dashboard/project/iaketsyhmqbwaabgykux/settings/general

  ✅ Discord alert sent

  Troubleshooting steps:
    1. Check Supabase Dashboard → Database → Replication
    2. Verify PostgREST is running in project settings
    3. Check for recent schema changes that may have errors
    4. Review Supabase logs for detailed error messages
```

---

## Discord Integration

Set `DISCORD_WEBHOOK_URL` in `.env.{env}` to enable alerts on recovery failures.

**Alert Format:**

```
🔥 CRITICAL: PostgREST Unhealthy
Environment: PROD
Status: Automated recovery failed
Action Required: Manual project restart

Dashboard: https://supabase.com/dashboard/project/...

Recovery Steps:
1. Go to Settings → Restart Project
2. Wait for restart to complete
3. Run health check again
```

If webhook URL is missing, the tool will print a warning but continue.

---

## CI/CD Integration

### Health Check in Deployment Pipeline

```yaml
- name: PostgREST Health Check
  run: |
    python -m tools.check_postgrest_health --env prod --json > health.json
    if [ $? -ne 0 ]; then
      echo "❌ PostgREST unhealthy after migration"
      exit 1
    fi
```

### Auto-Recovery After Migrations

```yaml
- name: Apply Migrations
  run: ./scripts/db_push.ps1 -SupabaseEnv prod

- name: Recover PostgREST Cache
  run: python -m tools.fix_schema_cache --env prod
```

---

## Manual Restart Procedure

If automated recovery fails:

1. **Go to Supabase Dashboard**

   - Prod: https://supabase.com/dashboard/project/iaketsyhmqbwaabgykux/settings/general
   - Dev: https://supabase.com/dashboard/project/ejiddanxtqcleyswqvkc/settings/general

2. **Click "Restart Project"**

   - Located in Settings → General
   - Takes ~2-3 minutes

3. **Wait for Restart**

   - Monitor status in dashboard
   - Services will be briefly unavailable

4. **Verify Recovery**

   ```powershell
   python -m tools.check_postgrest_health --env prod
   ```

5. **Document in Incident Log**
   - When: Timestamp
   - Trigger: What caused the stale cache
   - Resolution: Auto vs manual restart
   - Duration: How long until recovery

---

## Troubleshooting

### Health Probe Returns 401

✅ **This is EXPECTED and HEALTHY**

401 means:

- PostgREST is up and responding
- Schema cache is loaded
- RLS policies are enforcing auth

### Health Probe Timeout

Possible causes:

- Network connectivity issue
- Supabase project paused/suspended
- PostgREST service crashed

Action:

1. Check Supabase dashboard status
2. Verify project is not paused
3. Check network connectivity

### Recovery Fails Repeatedly

If manual restart also fails:

1. Check recent schema migrations for errors
2. Review Supabase logs for SQL errors
3. Verify database replication status
4. Contact Supabase support if infrastructure issue

### Discord Alerts Not Sending

Check:

1. `DISCORD_WEBHOOK_URL` set in `.env.{env}`
2. Webhook URL is valid and active
3. Network can reach Discord API
4. Review tool output for webhook errors

---

## Best Practices

1. **After Every Migration:** Run `fix_schema_cache` to prevent PGRST002
2. **In CI/CD:** Always check health after migrations
3. **Monitor:** Set up Discord webhook for prod failures
4. **Document:** Log all manual restarts for pattern analysis
5. **Preventive:** Consider running recovery operator on schedule (e.g., after every deployment)

---

## Related Files

- [`tools/check_postgrest_health.py`](../tools/check_postgrest_health.py) - Health probe implementation
- [`tools/fix_schema_cache.py`](../tools/fix_schema_cache.py) - Recovery operator implementation
- [`backend/services/data_layer.py`](../backend/services/data_layer.py) - HybridDataLayer with automatic failover
- [`backend/utils/alerting.py`](../backend/utils/alerting.py) - Discord alerting system

---

## Quick Reference

```powershell
# Check health
python -m tools.check_postgrest_health --env prod

# Auto-recover
python -m tools.fix_schema_cache --env prod

# After migrations (recommended)
./scripts/db_push.ps1 -SupabaseEnv prod
python -m tools.fix_schema_cache --env prod
python -m tools.check_postgrest_health --env prod --verbose
```

**Exit Code Legend:**

- `0` → ✅ Healthy / Recovery successful
- `1` → ❌ Unhealthy / Manual intervention needed
