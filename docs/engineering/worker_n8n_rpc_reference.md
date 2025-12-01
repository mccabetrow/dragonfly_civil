# Worker and n8n RPC Reference

## Overview

This document describes the **unified RPC functions** that workers and n8n workflows
MUST use for mutating core judgment data. Direct table writes are blocked by RLS;
all mutations must go through these service_role-only RPCs.

**Related Migrations:**

- `0200_core_judgment_schema.sql` - Core tables (core_judgments, debtor_intelligence, enforcement_actions)
- `0201_fcra_audit_log.sql` - FCRA audit table + `log_external_data_call` RPC
- `0202_fdcpa_contact_guard.sql` - FDCPA time check + communications table
- `0203_rls_force_core_judgment_tables.sql` - RLS hardening
- `0204_unified_worker_rpcs.sql` - Unified worker/n8n RPCs

---

## RPC Functions

### 1. `log_external_data_call` (FCRA Audit)

**Purpose:** Log every external skip-trace API call for FCRA compliance.

**When to call:** EVERY time you invoke an external data provider (idiCORE, TLOxp, Tracers, LexisNexis, etc.)

```sql
SELECT public.log_external_data_call(
    _judgment_id := 'uuid-of-judgment',
    _provider := 'idiCORE',
    _endpoint := '/person/search',
    _status := 'success',           -- 'success', 'error', 'timeout', 'rate_limited'
    _http_code := 200,
    _error_message := NULL,
    _meta := '{"query_type": "person", "results_count": 3}'::jsonb
);
-- Returns: UUID of the audit log entry
```

**n8n HTTP Request:**

```json
{
  "method": "POST",
  "url": "{{ $env.SUPABASE_URL }}/rest/v1/rpc/log_external_data_call",
  "headers": {
    "apikey": "{{ $env.SUPABASE_SERVICE_ROLE_KEY }}",
    "Authorization": "Bearer {{ $env.SUPABASE_SERVICE_ROLE_KEY }}",
    "Content-Type": "application/json"
  },
  "body": {
    "_judgment_id": "{{ $json.judgment_id }}",
    "_provider": "idiCORE",
    "_endpoint": "/person/search",
    "_status": "success",
    "_http_code": 200,
    "_meta": { "results_count": 1 }
  }
}
```

---

### 2. `fn_is_fdcpa_allowed_time` (FDCPA Check)

**Purpose:** Check if a timestamp is within the FDCPA-allowed contact window (8 AM - 9 PM debtor local time).

**When to call:** BEFORE sending any outbound communication to a debtor.

```sql
SELECT public.fn_is_fdcpa_allowed_time(
    _ts := now(),
    _debtor_timezone := 'America/New_York'
);
-- Returns: BOOLEAN (true if contact allowed)
```

**n8n usage:** Call this RPC before any outbound SMS, email, or phone. If it returns `false`, DO NOT send the message.

---

### 3. `upsert_debtor_intelligence`

**Purpose:** Insert or update debtor intelligence for a judgment.

**When to call:** After receiving enrichment data from a skip-trace vendor.

```sql
SELECT public.upsert_debtor_intelligence(
    _judgment_id := 'uuid-of-judgment',
    _data_source := 'idicore',
    _employer_name := 'Delta Airlines',
    _employer_address := 'JFK Terminal 4',
    _income_band := '$75k-100k',
    _bank_name := NULL,
    _bank_address := NULL,
    _home_ownership := 'renter',
    _has_benefits_only := false,
    _confidence_score := 85.0,
    _is_verified := false
);
-- Returns: UUID of the debtor_intelligence record
```

---

### 4. `update_judgment_status`

**Purpose:** Update a judgment's status and optional collectability score.

**When to call:** When judgment status changes (e.g., after enrichment, payment, or expiration).

```sql
SELECT public.update_judgment_status(
    _judgment_id := 'uuid-of-judgment',
    _status := 'partially_satisfied',  -- Valid: unsatisfied, partially_satisfied, satisfied, vacated, expired, on_hold
    _collectability_score := 75,       -- Optional, 0-100
    _note := 'Enrichment complete'     -- Optional, for audit trail
);
-- Returns: BOOLEAN (true on success)
```

---

### 5. `log_enforcement_action`

**Purpose:** Log a new enforcement action for a judgment.

**When to call:** When generating or serving enforcement documents.

```sql
SELECT public.log_enforcement_action(
    _judgment_id := 'uuid-of-judgment',
    _action_type := 'income_execution',  -- Valid: information_subpoena, restraining_notice, property_execution, income_execution, bank_levy, real_property_lien, demand_letter, settlement_offer, skiptrace, asset_search, other
    _status := 'pending',                -- Valid: planned, pending, served, completed, failed, cancelled, expired
    _requires_attorney_signature := true,
    _generated_url := 'https://storage.example.com/docs/ie_12345.pdf',
    _notes := 'Sent to employer Delta Airlines',
    _metadata := '{"employer_ein": "XX-XXXXXXX"}'::jsonb
);
-- Returns: UUID of the enforcement_actions record
```

---

### 6. `complete_enrichment` (Combined RPC)

**Purpose:** Perform the full enrichment completion flow in a single transaction:

1. Log FCRA audit trail
2. Upsert debtor intelligence
3. Update judgment status

**When to call:** At the end of an enrichment worker run.

```sql
SELECT public.complete_enrichment(
    _judgment_id := 'uuid',
    -- FCRA audit fields
    _provider := 'idiCORE',
    _endpoint := '/person/search',
    _fcra_status := 'success',
    _fcra_http_code := 200,
    _fcra_meta := '{"results_count": 1}'::jsonb,
    -- Intelligence fields
    _data_source := 'idicore',
    _employer_name := 'Delta Airlines',
    _employer_address := 'JFK Terminal 4',
    _income_band := '$75k-100k',
    _confidence_score := 85.0,
    -- Status update
    _new_status := 'unsatisfied',
    _new_collectability_score := 75
);
-- Returns: jsonb { fcra_log_id, intelligence_id, status_updated }
```

**n8n HTTP Request:**

```json
{
  "method": "POST",
  "url": "{{ $env.SUPABASE_URL }}/rest/v1/rpc/complete_enrichment",
  "headers": {
    "apikey": "{{ $env.SUPABASE_SERVICE_ROLE_KEY }}",
    "Authorization": "Bearer {{ $env.SUPABASE_SERVICE_ROLE_KEY }}",
    "Content-Type": "application/json"
  },
  "body": {
    "_judgment_id": "{{ $json.judgment_id }}",
    "_provider": "idiCORE",
    "_endpoint": "/person/search",
    "_fcra_status": "success",
    "_fcra_http_code": 200,
    "_fcra_meta": { "results_count": 1 },
    "_data_source": "idicore",
    "_employer_name": "{{ $json.employer_name }}",
    "_employer_address": "{{ $json.employer_address }}",
    "_income_band": "{{ $json.income_band }}",
    "_confidence_score": 85.0,
    "_new_collectability_score": 75
  }
}
```

---

## Plaintiff Management RPCs (Migration 0205)

### 7. `update_plaintiff_status`

**Purpose:** Atomically update plaintiff status and write to status history.

**When to call:** When changing a plaintiff's status from n8n workflows.

```sql
SELECT public.update_plaintiff_status(
    p_plaintiff_id := 'uuid-of-plaintiff',
    p_new_status := 'contacted',
    p_note := 'Auto intake processing',
    p_changed_by := 'dragonfly_new_plaintiff_intake_v1'
);
-- Returns: jsonb { success, plaintiff_id, old_status, new_status, history_id, changed }
```

**n8n HTTP Request:**

```json
{
  "method": "POST",
  "url": "{{ $env.SUPABASE_URL }}/rest/v1/rpc/update_plaintiff_status",
  "headers": {
    "apikey": "{{ $env.SUPABASE_SERVICE_ROLE_KEY }}",
    "Authorization": "Bearer {{ $env.SUPABASE_SERVICE_ROLE_KEY }}",
    "Content-Type": "application/json"
  },
  "body": {
    "p_plaintiff_id": "{{ $json.plaintiff_id }}",
    "p_new_status": "contacted",
    "p_note": "Auto intake processing",
    "p_changed_by": "dragonfly_new_plaintiff_intake_v1"
  }
}
```

---

### 8. `upsert_plaintiff_task`

**Purpose:** Create or update a plaintiff task with idempotency on open tasks.

**When to call:** When scheduling or updating plaintiff tasks from n8n planners.

```sql
SELECT public.upsert_plaintiff_task(
    p_plaintiff_id := 'uuid-of-plaintiff',
    p_kind := 'call',
    p_due_at := now() + interval '1 day',
    p_metadata := '{"priority": "high"}'::jsonb,
    p_created_by := 'dragonfly_call_task_planner_v1'
);
-- Returns: jsonb { success, task_id, plaintiff_id, kind, is_new }
```

**n8n HTTP Request:**

```json
{
  "method": "POST",
  "url": "{{ $env.SUPABASE_URL }}/rest/v1/rpc/upsert_plaintiff_task",
  "headers": {
    "apikey": "{{ $env.SUPABASE_SERVICE_ROLE_KEY }}",
    "Authorization": "Bearer {{ $env.SUPABASE_SERVICE_ROLE_KEY }}",
    "Content-Type": "application/json"
  },
  "body": {
    "p_plaintiff_id": "{{ $json.plaintiff_id }}",
    "p_kind": "call",
    "p_due_at": "{{ $now.plus(1, 'day').toISO() }}",
    "p_metadata": { "priority": "high" },
    "p_created_by": "dragonfly_call_task_planner_v1"
  }
}
```

---

### 9. `complete_plaintiff_task`

**Purpose:** Mark a plaintiff task as completed with optional outcome and notes.

**When to call:** When operators complete call tasks or when workflows close tasks.

```sql
SELECT public.complete_plaintiff_task(
    p_task_id := 'uuid-of-task',
    p_outcome := 'left_voicemail',
    p_notes := 'VM left at 2:30pm',
    p_completed_by := 'operator_jane'
);
-- Returns: jsonb { success, task_id, plaintiff_id, kind, outcome, changed }
```

---

### 10. `advance_import_run`

**Purpose:** Move an import_run through valid status transitions.

**When to call:** When updating import workflow status from n8n.

```sql
SELECT public.advance_import_run(
    p_import_run_id := 'uuid-of-import-run',
    p_new_status := 'processing',
    p_metadata := '{"queued_at": "2025-01-15T10:00:00Z"}'::jsonb
);
-- Returns: jsonb { success, import_run_id, old_status, new_status }
```

**Valid transitions:**

- `pending` → `ready_for_queue`, `queued`, `cancelled`
- `ready_for_queue` → `queued`, `processing`, `cancelled`
- `queued` → `processing`, `failed`, `cancelled`
- `processing` → `completed`, `failed`

---

## Security Model

| Role            | SELECT | INSERT       | UPDATE       | DELETE       |
| --------------- | ------ | ------------ | ------------ | ------------ |
| `anon`          | ❌     | ❌           | ❌           | ❌           |
| `authenticated` | ✅     | ❌           | ❌           | ❌           |
| `service_role`  | ✅     | ✅ (via RPC) | ✅ (via RPC) | ✅ (via RPC) |

**Key points:**

- All PII tables have RLS ENABLED and FORCED
- Workers and n8n connect with `service_role` credentials
- Use RPCs for mutations; direct table writes are blocked for non-service_role
- Audit tables (`external_data_calls`, `communications`) are append-only (no UPDATE/DELETE)

---

## Error Handling

All RPCs will raise exceptions if:

- `_judgment_id` does not exist in `core_judgments`
- Invalid enum values are passed for status or action_type
- Required parameters are missing

Workers should catch these exceptions and log appropriately:

```python
try:
    result = client.rpc("complete_enrichment", {...}).execute()
except Exception as e:
    logger.error(f"Enrichment failed for judgment {judgment_id}: {e}")
    # Log error to external_data_calls with status='error'
```

---

## Migration Checklist

Before deploying workers that use these RPCs:

1. ✅ Apply migration `0200_core_judgment_schema.sql`
2. ✅ Apply migration `0201_fcra_audit_log.sql`
3. ✅ Apply migration `0202_fdcpa_contact_guard.sql`
4. ✅ Apply migration `0203_rls_force_core_judgment_tables.sql`
5. ✅ Apply migration `0204_unified_worker_rpcs.sql`
6. ✅ Apply migration `0205_plaintiff_rpcs.sql`
7. ✅ Run `python -m tools.check_schema_consistency --env dev`
8. ✅ Run `python scripts/check_prod_schema.py --env prod`

---

## n8n Flow Migration Map

| n8n Flow                    | Node to Replace             | Use RPC                   |
| --------------------------- | --------------------------- | ------------------------- |
| `new_lead_enrichment_v1`    | Insert Debtor Intelligence  | `complete_enrichment`     |
| `new_lead_enrichment_v1`    | Update Judgment: ACTIONABLE | `complete_enrichment`     |
| `enforcement_escalation_v1` | Touch Next Action           | `log_enforcement_action`  |
| `new_plaintiff_intake_v1`   | Update Plaintiff Status     | `update_plaintiff_status` |
| `new_plaintiff_intake_v1`   | Record Intake Status        | _(merged into above)_     |
| `call_task_planner_v1`      | Backfill tasks              | `upsert_plaintiff_task`   |
| `import_trigger_v1`         | Mark Import Run             | `advance_import_run`      |

See `docs/n8n_bridge_mapping.md` for full analysis.
