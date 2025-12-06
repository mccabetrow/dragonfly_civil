# Dragonfly Production Parity Deployment Guide

**Generated:** 2025-07-01  
**Purpose:** Make PRODUCTION behave IDENTICALLY to dev

---

## Summary of Changes

### Phase 1: CORS Hardening ✅

**Files Modified:**

- `backend/config.py` - Added `dragonfly_cors_origins` field and `cors_allowed_origins` property
- `backend/main.py` - Updated CORSMiddleware to use ENV-driven origins

**Railway Environment Variable to Set:**

```bash
DRAGONFLY_CORS_ORIGINS=https://dragonfly-console1.vercel.app,https://dragonfly-console1-git-main-mccabetrow.vercel.app,http://localhost:5173
```

> ⚠️ **Important:** Replace `mccabetrow` with your actual Vercel username if different.

### Phase 2: Supabase Schema Parity ✅

**Problem:** Migrations were marked as "applied" but schema objects didn't exist (likely transaction rollback).

**Solution:** Re-ran `20251214000000_repair_schema_drift.sql` and created missing views directly.

**Views Created/Verified:**
| View | Status |
|------|--------|
| `v_metrics_intake_daily` | ✅ Created |
| `v_metrics_pipeline` | ✅ Exists |
| `v_enforcement_pipeline_status` | ✅ Created |
| `v_offer_stats` | ✅ Created |
| `v_radar` | ✅ Created |
| `v_enrichment_health` | ✅ Exists |
| `events` | ✅ Created (table) |
| `v_plaintiffs_overview` | ✅ Exists |
| `v_enforcement_overview` | ✅ Exists |
| `v_plaintiff_call_queue` | ✅ Exists |
| `v_judgment_pipeline` | ✅ Exists |
| `v_collectability_snapshot` | ✅ Exists |

**Scripts Created:**

- `scripts/repair_prod_views.py` - Creates missing views idempotently
- `scripts/verify_prod_schema.py` - Verifies critical views exist and reloads PostgREST

### Phase 3: Frontend Build ✅

Dashboard builds successfully with `npm run build`.

---

## Deployment Commands

### 1. Set Railway CORS Environment Variable

In Railway dashboard → dragonfly-backend → Variables:

```
DRAGONFLY_CORS_ORIGINS=https://dragonfly-console1.vercel.app,https://dragonfly-console1-git-main-mccabetrow.vercel.app,http://localhost:5173
```

### 2. Redeploy Railway Backend

Railway will auto-redeploy when env vars change. If not:

```bash
# Trigger redeploy from Railway dashboard or CLI
railway up
```

### 3. Verify Supabase Prod Schema (Already Done)

```powershell
# Verify all views exist
.\scripts\load_env.ps1
$env:SUPABASE_MODE = 'prod'
python scripts\verify_prod_schema.py
```

### 4. Verify Vercel Deployment

Vercel auto-deploys from `main` branch. Check:

- https://dragonfly-console1.vercel.app

---

## Smoke Test Checklist

Run these after deployment:

| Test              | Command/Action                                             | Expected                                  |
| ----------------- | ---------------------------------------------------------- | ----------------------------------------- |
| CORS preflight    | Open Vercel console in browser, check DevTools Network tab | No CORS errors                            |
| Health endpoint   | `curl https://dragonfly-backend.railway.app/health`        | `{"status": "healthy"}`                   |
| Executive metrics | Navigate to CEO dashboard                                  | Charts load without 404/400 errors        |
| Plaintiff list    | Navigate to Plaintiffs page                                | Table loads with data                     |
| Events feed       | CEO overview activity feed                                 | Events render (or empty state, not error) |
| Offers stats      | Enforcement/Offers page                                    | Stats render (stubs return zeros for now) |

---

## Rollback Plan

### CORS

Remove `DRAGONFLY_CORS_ORIGINS` from Railway → Falls back to localhost only.

### Supabase Views

Views are additive (CREATE OR REPLACE). No rollback needed unless views break queries.

---

## Files Changed (Commit Summary)

```
backend/config.py        # Added CORS config
backend/main.py          # ENV-driven CORS origins
scripts/repair_prod_views.py    # New: repair missing views
scripts/verify_prod_schema.py   # New: verify schema
```

---

## Next Steps (Optional)

1. **Update schema_freeze.json** - Capture new prod baseline:

   ```powershell
   $env:SUPABASE_MODE = 'prod'
   python -m tools.check_schema_consistency --env prod --freeze
   ```

2. **Add real implementations** - Replace stub views (`v_offer_stats`, `v_radar`) with real queries once offer engine is live.

3. **CI/CD Integration** - Add `verify_prod_schema.py` to preflight checks.

---

**Status:** ✅ Ready for production deployment
