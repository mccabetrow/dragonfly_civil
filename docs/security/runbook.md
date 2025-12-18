# Dragonfly Security Runbook

## Overview

This runbook describes how to interpret and triage Supabase Security Advisor findings for the Dragonfly Civil platform. It provides step-by-step guidance for resolving common security issues while maintaining production stability.

## Quick Reference

| Finding Type           | Severity | Auto-Fix Available | SLA    |
| ---------------------- | -------- | ------------------ | ------ |
| RLS Disabled           | Critical | Yes                | 24h    |
| RLS Not Forced         | High     | Yes                | 48h    |
| Overly-Broad Grants    | High     | Yes                | 48h    |
| SECURITY DEFINER Risk  | Medium   | Manual Review      | 1 week |
| Exposed Views          | Medium   | Yes                | 72h    |
| Storage Policy Missing | Medium   | Yes                | 72h    |

## Running the Security Audit

### Prerequisites

```powershell
# Ensure env is loaded
.\scripts\load_env.ps1

# Activate virtual environment
.\.venv\Scripts\Activate.ps1
```

### Run Audit

```powershell
# Against dev
python -m tools.security_audit --env dev

# Against prod (use caution)
python -m tools.security_audit --env prod
```

### Interpreting Output

The audit prints each relation with its security posture:

```
[security_audit] relation=judgments kind=table rls=on forced=yes
    policies:
      - judgments_service_all cmd=ALL roles=public permissive=yes
    grants:
      - authenticated: SELECT
      - service_role: DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE
```

**Key fields:**

- `rls=on/off`: Row-Level Security enabled
- `forced=yes/no`: RLS applies even to table owner
- `policies`: Active RLS policies
- `grants`: Role privileges

## Finding Categories

### 1. RLS Disabled (`rls=off`)

**Risk:** All rows visible to anyone with table access.

**Remediation:**

```sql
ALTER TABLE public.<table_name> ENABLE ROW LEVEL SECURITY;
```

**Verification:**

```sql
SELECT relname, relrowsecurity
FROM pg_class
WHERE relname = '<table_name>';
```

**Rollback:**

```sql
ALTER TABLE public.<table_name> DISABLE ROW LEVEL SECURITY;
```

### 2. RLS Not Forced (`forced=no`)

**Risk:** Table owner bypasses RLS policies.

**Remediation:**

```sql
ALTER TABLE public.<table_name> FORCE ROW LEVEL SECURITY;
```

**Verification:**

```sql
SELECT relname, relforcerowsecurity
FROM pg_class
WHERE relname = '<table_name>';
```

**Rollback:**

```sql
ALTER TABLE public.<table_name> NO FORCE ROW LEVEL SECURITY;
```

### 3. Overly-Broad Grants

**Risk:** Roles have more privileges than needed (INSERT, UPDATE, DELETE on read-only tables).

**Common Violations:**

- `anon` or `authenticated` having write access to core tables
- Views with full privileges instead of SELECT-only

**Remediation:**

```sql
-- Remove write access
REVOKE INSERT, UPDATE, DELETE ON public.<table_name> FROM anon;
REVOKE INSERT, UPDATE, DELETE ON public.<table_name> FROM authenticated;

-- For views, restrict to SELECT only
REVOKE ALL ON public.<view_name> FROM anon;
REVOKE ALL ON public.<view_name> FROM authenticated;
GRANT SELECT ON public.<view_name> TO authenticated;
```

**Verification:**

```sql
SELECT table_name, grantee, privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'public'
  AND table_name = '<table_name>'
  AND grantee IN ('anon', 'authenticated');
```

**Rollback:**

```sql
-- Restore write access (use with caution)
GRANT INSERT, UPDATE, DELETE ON public.<table_name> TO authenticated;
```

### 4. SECURITY DEFINER Risks

**Risk:** Functions run with definer's privileges, potentially bypassing RLS.

**Triage Checklist:**

1. Is the function exposed via PostgREST (public schema)?
2. Does it accept user input without validation?
3. Does it operate on sensitive tables?
4. Does it need SECURITY DEFINER, or can it use SECURITY INVOKER?

**Safe Pattern:**

```sql
CREATE OR REPLACE FUNCTION public.safe_function(p_id uuid)
RETURNS SETOF public.some_table
LANGUAGE plpgsql
SECURITY INVOKER  -- Runs as calling user, respects RLS
AS $$
BEGIN
    RETURN QUERY SELECT * FROM public.some_table WHERE id = p_id;
END;
$$;
```

**If SECURITY DEFINER is required:**

```sql
CREATE OR REPLACE FUNCTION public.admin_function(p_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public  -- Prevent search_path attacks
AS $$
BEGIN
    -- Validate input
    IF p_id IS NULL THEN
        RAISE EXCEPTION 'Invalid input';
    END IF;

    -- Perform privileged operation
    UPDATE public.some_table SET processed = true WHERE id = p_id;
END;
$$;

-- Restrict who can call it
REVOKE ALL ON FUNCTION public.admin_function(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.admin_function(uuid) TO service_role;
```

### 5. Exposed Views

**Risk:** Views exposing sensitive data to public roles.

**View Classification:**

| Category        | Access Level             | Examples                                   |
| --------------- | ------------------------ | ------------------------------------------ |
| Dashboard Views | SELECT for authenticated | v_plaintiffs_overview, v_judgment_pipeline |
| Internal Views  | service_role only        | v_priority_pipeline, v_radar               |
| Metrics Views   | service_role only        | v*ceo_financial_summary, v_metrics*\*      |

**Remediation:**

```sql
-- Dashboard views: SELECT only
REVOKE ALL ON public.<view_name> FROM anon, authenticated;
GRANT SELECT ON public.<view_name> TO authenticated;

-- Internal views: no public access
REVOKE ALL ON public.<view_name> FROM anon, authenticated;
```

### 6. Storage Policies

**Risk:** Storage buckets without proper access controls.

**Audit Command:**

```sql
SELECT name, public, file_size_limit, allowed_mime_types
FROM storage.buckets;

SELECT bucket_id, name, definition
FROM storage.policies;
```

**Safe Pattern:**

```sql
-- Create private bucket
INSERT INTO storage.buckets (id, name, public)
VALUES ('evidence', 'evidence', false);

-- Allow service_role only
CREATE POLICY "Service role access"
ON storage.objects FOR ALL
TO service_role
USING (bucket_id = 'evidence');
```

## Dragonfly-Specific Policies

### Key Tables

| Table                | RLS | Forced | Write Access |
| -------------------- | --- | ------ | ------------ |
| judgments            | ✅  | ✅     | service_role |
| plaintiffs           | ✅  | ✅     | service_role |
| enforcement_cases    | ✅  | ✅     | service_role |
| enforcement_evidence | ✅  | ✅     | service_role |
| import_runs          | ✅  | ✅     | service_role |
| plaintiff_tasks      | ✅  | ✅     | service_role |

### Pipeline Views (Dashboard)

These views must remain accessible for the dashboard:

- `v_plaintiffs_overview`
- `v_judgment_pipeline`
- `v_enforcement_overview`
- `v_enforcement_recent`
- `v_plaintiff_call_queue`

**Required grants:**

```sql
GRANT SELECT ON public.<view_name> TO authenticated;
-- Optionally: GRANT SELECT ON public.<view_name> TO anon;
```

### Restricted Tables

These tables must NEVER have anon/authenticated/public access:

- `import_runs` (ops metadata)
- `enforcement_evidence` (sensitive documents)
- `access_logs` (audit trail)
- `dragonfly_role_audit_log` (security audit)

## Migration Workflow

### 1. Create Migration

```powershell
# Generate timestamp
$ts = Get-Date -Format 'yyyyMMddHHmmss'
$file = "supabase/migrations/${ts}_security_fix_<description>.sql"
New-Item -Path $file -ItemType File
code $file
```

### 2. Test in Dev

```powershell
# Apply to dev
$env:SUPABASE_MODE = 'dev'
.\scripts\db_push.ps1 -SupabaseEnv dev

# Verify
python -m tools.security_audit --env dev
```

### 3. Validate Dashboard

```powershell
cd dragonfly-dashboard
npm run build
npm run preview
```

Manually verify:

- [ ] Dashboard loads without errors
- [ ] Key views display data
- [ ] No 403/401 errors in console

### 4. Promote to Prod

```powershell
# Full preflight
.\scripts\preflight_prod.ps1

# Apply migrations
$env:SUPABASE_MODE = 'prod'
.\scripts\db_push.ps1 -SupabaseEnv prod

# Verify
python -m tools.security_audit --env prod
```

## Emergency Rollback

If a security migration breaks production:

### 1. Identify the Breaking Change

```powershell
# Check recent migrations
git log --oneline -10 -- supabase/migrations/
```

### 2. Apply Rollback SQL

Each migration includes rollback statements at the bottom. Connect directly:

```powershell
# Get connection string
$env:SUPABASE_MODE = 'prod'
python -c "from src.supabase_client import get_supabase_db_url; print(get_supabase_db_url('prod'))"

# Connect and run rollback
psql "<connection_string>"
```

### 3. Document the Incident

Create an issue documenting:

- What broke
- Root cause
- Rollback applied
- Follow-up actions

## CI/CD Integration

The security audit runs in CI via `.github/workflows/env-schema-check.yml`:

```yaml
security-audit:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - name: Run Security Audit
      run: |
        python -m tools.security_audit --env dev
```

**Expected behavior:**

- Warnings → CI passes with annotations
- Violations in KEY_TABLE_POLICIES → CI fails

## Contacts

- **Security Questions:** @mccabetrow
- **On-call for Prod Issues:** See #dragonfly-ops

## Appendix: Full Audit SQL

```sql
-- List all tables with RLS status
SELECT
    c.relname AS table_name,
    c.relrowsecurity AS rls_enabled,
    c.relforcerowsecurity AS rls_forced
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind = 'r'
ORDER BY c.relname;

-- List all policies
SELECT
    schemaname,
    tablename,
    policyname,
    cmd,
    roles,
    permissive
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename, policyname;

-- List all grants
SELECT
    table_name,
    grantee,
    privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'public'
  AND grantee IN ('anon', 'authenticated', 'service_role', 'public')
ORDER BY table_name, grantee, privilege_type;

-- Find SECURITY DEFINER functions
SELECT
    p.proname AS function_name,
    p.prosecdef AS security_definer,
    pg_get_functiondef(p.oid) AS definition
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.prosecdef = true;
```
