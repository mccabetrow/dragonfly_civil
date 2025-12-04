# =============================================================================

# Dragonfly Civil – RLS Schema Diff Preview

# BEFORE → AFTER Behavior Analysis

# =============================================================================

## Executive Summary

This document describes the BEFORE and AFTER behavior of database access
following the enterprise-grade RLS deployment.

---

## BEFORE: Current State (Pre-Migration)

### Access Control Model

- **RLS Status**: Partially enabled, not consistently enforced
- **Role Model**: Simple `auth.role()` checks (anon/authenticated/service_role)
- **Column Protection**: None – all columns accessible if row access granted
- **Audit Trail**: Limited – no centralized role assignment tracking

### Table Access (Current)

| Table                      | anon   | authenticated  | service_role |
| -------------------------- | ------ | -------------- | ------------ |
| public.judgments           | SELECT | SELECT         | ALL          |
| public.plaintiffs          | SELECT | SELECT         | ALL          |
| public.enforcement_cases   | SELECT | SELECT, UPDATE | ALL          |
| public.plaintiff_tasks     | SELECT | SELECT         | ALL          |
| public.debtor_intelligence | -      | -              | ALL          |
| public.external_data_calls | -      | -              | ALL          |

### Vulnerabilities

1. ❌ Any authenticated user can read all judgment data
2. ❌ No distinction between ops, CEO, and bot access
3. ❌ No column-level protection for financial data
4. ❌ No audit trail for who accessed what
5. ❌ Bots have same access as human users

---

## AFTER: New State (Post-Migration)

### Access Control Model

- **RLS Status**: Enabled AND FORCED on all tables
- **Role Model**: Custom RBAC via `dragonfly_role_mappings` table
- **Column Protection**: Enforced via SECURITY DEFINER RPCs
- **Audit Trail**: Full audit log in `dragonfly_role_audit_log`

### Roles Defined

| Role             | Description         | Capabilities                               |
| ---------------- | ------------------- | ------------------------------------------ |
| `admin`          | Full system access  | SELECT, INSERT, UPDATE, DELETE on all      |
| `ops`            | Operations team     | SELECT all, UPDATE operational fields only |
| `ceo`            | Executive read-only | SELECT all financial/case data             |
| `enrichment_bot` | Data enrichment     | SELECT, UPDATE enrichment fields only      |
| `outreach_bot`   | Call automation     | SELECT, INSERT/UPDATE call outcomes only   |
| `service_role`   | Backend/n8n         | Full access (bypasses RLS)                 |

### Table Access (New)

| Table                          | anon | authenticated (no role) | ops              | ceo    | enrichment_bot   | outreach_bot           | admin  | service_role |
| ------------------------------ | ---- | ----------------------- | ---------------- | ------ | ---------------- | ---------------------- | ------ | ------------ |
| public.judgments               | ❌   | ❌                      | SELECT, UPDATE\* | SELECT | SELECT, UPDATE\* | SELECT                 | ALL    | ALL          |
| public.plaintiffs              | ❌   | ❌                      | SELECT, UPDATE\* | SELECT | SELECT           | SELECT                 | ALL    | ALL          |
| public.enforcement_cases       | ❌   | ❌                      | SELECT, UPDATE\* | SELECT | SELECT           | SELECT                 | ALL    | ALL          |
| public.plaintiff_tasks         | ❌   | ❌                      | ALL              | SELECT | SELECT           | SELECT                 | ALL    | ALL          |
| public.plaintiff_call_attempts | ❌   | ❌                      | SELECT, INSERT   | SELECT | SELECT           | SELECT, INSERT, UPDATE | ALL    | ALL          |
| public.debtor_intelligence     | ❌   | ❌                      | SELECT           | SELECT | ALL              | SELECT                 | ALL    | ALL          |
| public.external_data_calls     | ❌   | ❌                      | ❌               | ❌     | INSERT           | ❌                     | SELECT | ALL          |
| public.outreach_log            | ❌   | ❌                      | ALL              | SELECT | SELECT           | ALL                    | ALL    | ALL          |

\*UPDATE via column-guarded RPCs only

### Column-Level Restrictions

#### OPS Role (via `ops_update_judgment` RPC)

- ✅ Can update: `enforcement_stage`, `priority_level`
- ❌ Cannot update: `judgment_amount`, `entry_date`, `defendant_name`, `plaintiff_name`

#### Enrichment Bot (via `enrichment_update_debtor` RPC)

- ✅ Can update: `employer_name`, `bank_name`, `property_records`, `vehicle_records`, `income_estimate`
- ❌ Cannot update: `status`, `enforcement_stage`, `assignee`

#### Outreach Bot (via `outreach_log_call` RPC)

- ✅ Can update: `outcome`, `interest_level`, `notes`, `next_follow_up_at`
- ❌ Cannot update: judgment or plaintiff financial fields

#### CEO Role

- ✅ Can read: All tables
- ❌ Cannot update: Any table
- ❌ Cannot delete: Any record

---

## Migration Compatibility

### Views (Dashboard)

All dashboard views set to `security_invoker = false`:

- ✅ `v_plaintiffs_overview` – readable by authenticated
- ✅ `v_enforcement_overview` – readable by authenticated
- ✅ `v_judgment_pipeline` – readable by authenticated
- ✅ `v_plaintiff_call_queue` – readable by authenticated
- ✅ `v_metrics_*` – readable by authenticated

### RPCs (n8n/Workers)

All SECURITY DEFINER RPCs continue to work:

- ✅ `queue_job()` – service_role only
- ✅ `dequeue_job()` – service_role only
- ✅ `spawn_enforcement_flow()` – service_role only
- ✅ `log_call_outcome()` – service_role only
- ✅ `generate_enforcement_tasks()` – service_role only

### Breaking Changes

1. **Anonymous users** can no longer read any data
2. **Authenticated users without role** can no longer read any data
3. **Direct table UPDATEs** now require role-specific RPCs
4. **DELETE operations** now require admin or service_role

---

## Role Assignment

To grant a role to a user:

```sql
INSERT INTO public.dragonfly_role_mappings (user_id, role, granted_by)
VALUES (
    'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',  -- auth.uid()
    'ops',                                    -- role name
    'admin@dragonfly.com'                    -- who granted it
);
```

To revoke a role:

```sql
UPDATE public.dragonfly_role_mappings
SET is_active = false
WHERE user_id = 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
  AND role = 'ops';
```

---

## Security Guarantees

1. ✅ **Zero Trust**: No access without explicit role mapping
2. ✅ **Least Privilege**: Roles only grant minimum necessary access
3. ✅ **Audit Trail**: All role changes logged to `dragonfly_role_audit_log`
4. ✅ **Column Protection**: Financial data protected from ops/bot modification
5. ✅ **Bot Isolation**: Bots can only modify their designated fields
6. ✅ **Service Role Preserved**: n8n/workers continue to work via service_role

---

## Test Verification

Run the RLS test suite:

```bash
pytest tests/test_rls_policies.py -v
```

Verify in production:

```sql
-- Check current user's roles
SELECT * FROM public.dragonfly_role_mappings
WHERE user_id = auth.uid() AND is_active = true;

-- Test read access
SELECT public.dragonfly_can_read();

-- Test specific role
SELECT public.dragonfly_has_role('ops');
```
