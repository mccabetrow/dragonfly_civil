# Security Invoker Verification Checklist

## Overview

Migration [20261001_enforce_invoker_views.sql](../supabase/migrations/20261001_enforce_invoker_views.sql) converted all views in operational schemas from `SECURITY DEFINER` to `SECURITY INVOKER`.

## Current Status (Verified)

✅ **96 views** across all exposed schemas are correctly configured with `security_invoker=true`
✅ **0 views** remain with `SECURITY DEFINER` mode

## Verification Steps

### 1. Run Automated Verification Script

```powershell
$env:SUPABASE_MODE='dev'
python verify_security_invoker.py --env dev
```

Expected output:

```
Total views checked: 96
✅ INVOKER (correct): 96
❌ DEFINER (needs fix): 0
```

### 2. Verify in Supabase Dashboard

1. Navigate to **SQL Editor** in Supabase Dashboard
2. Run the following verification query:

```sql
SELECT
    n.nspname AS schema,
    COUNT(*) AS total_views,
    COUNT(*) FILTER (WHERE c.reloptions @> ARRAY['security_invoker=true']) AS invoker_count,
    COUNT(*) FILTER (WHERE NOT c.reloptions @> ARRAY['security_invoker=true']) AS definer_count
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'v'
  AND n.nspname IN ('public', 'intake', 'enforcement', 'legal', 'rag', 'evidence', 'workers', 'ops', 'analytics')
GROUP BY n.nspname
ORDER BY n.nspname;
```

Expected result: All schemas should show `definer_count = 0`

### 3. Check Supabase Security Advisor

1. Navigate to **Settings** → **Database** → **Security Advisor**
2. Verify there are **no warnings** about "Security Definer Views"
3. If warnings persist:
   - Click "Refresh" to update the advisor cache
   - Wait 5-10 minutes for PostgREST schema cache to reload
   - Run `SELECT pg_notify('pgrst', 'reload schema')` to force cache refresh

### 4. Verify PostgREST API Endpoints

All views should remain accessible through PostgREST with no API breakage:

```bash
# Test a sample view endpoint (replace with your URL)
curl "https://your-project.supabase.co/rest/v1/v_plaintiffs_overview?select=*&limit=1" \
  -H "apikey: YOUR_ANON_KEY" \
  -H "Authorization: Bearer YOUR_ANON_KEY"
```

Expected: 200 OK response with data (respecting RLS policies)

## Affected Schemas

- ✅ `public` - Main application tables and views
- ✅ `intake` - Plaintiff intake pipeline
- ✅ `enforcement` - Judgment enforcement operations
- ✅ `legal` - Legal compliance and FCRA/FDCPA
- ✅ `rag` - RAG knowledge base
- ✅ `evidence` - Evidence tracking
- ✅ `workers` - Background job observability
- ✅ `ops` - Operations monitoring (private, but still secure)
- ✅ `analytics` - Reporting and metrics

## What Changed

### Before

```sql
CREATE VIEW public.v_example AS
SELECT * FROM public.judgments;
-- Default behavior: SECURITY DEFINER
-- Bypasses RLS using view owner's permissions ⚠️
```

### After

```sql
ALTER VIEW public.v_example SET (security_invoker = true);
-- New behavior: SECURITY INVOKER
-- Respects the calling user's RLS policies ✅
```

## Security Impact

✅ **Improved Security**: Views now respect Row-Level Security (RLS) policies of the calling user
✅ **Least Privilege**: Anonymous and authenticated users only see data they're authorized to access
✅ **Audit Trail**: All data access is properly attributed to the calling role
✅ **Defense in Depth**: Even if a view is misconfigured, RLS acts as the final security boundary

## Rollback Plan (If Needed)

If a view **requires** definer semantics (very rare), follow this pattern:

1. **Don't** revert the view to SECURITY DEFINER
2. **Do** create a SECURITY DEFINER function that wraps the sensitive logic:

```sql
-- ❌ BAD: Reverting view to SECURITY DEFINER
-- ALTER VIEW public.v_sensitive SET (security_invoker = false);

-- ✅ GOOD: Wrap sensitive logic in a controlled function
CREATE OR REPLACE FUNCTION ops.privileged_operation(param1 TEXT)
RETURNS SETOF record
LANGUAGE SQL
SECURITY DEFINER
SET search_path = ops, public
AS $$
  -- Sensitive logic with elevated permissions
  SELECT * FROM ops.private_table WHERE condition = param1;
$$;

-- Grant explicit access
GRANT EXECUTE ON FUNCTION ops.privileged_operation TO dragonfly_app;

-- View remains SECURITY INVOKER and calls the function
CREATE OR REPLACE VIEW public.v_safe_wrapper
WITH (security_invoker = true) AS
SELECT * FROM ops.privileged_operation('some_param');
```

## References

- [Supabase RLS Documentation](https://supabase.com/docs/guides/database/postgres/row-level-security#security-invoker-views)
- [PostgreSQL SECURITY INVOKER](https://www.postgresql.org/docs/current/sql-createview.html)
- Migration: [20261001_enforce_invoker_views.sql](../supabase/migrations/20261001_enforce_invoker_views.sql)

## Last Verified

- **Date**: 2026-01-11
- **Environment**: dev
- **Result**: ✅ All 96 views correctly configured
- **Verified By**: verify_security_invoker.py
