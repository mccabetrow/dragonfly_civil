# n8n Bridge Mapping: Node → RPC / PGMQ Conversion

> **Purpose**: Audit of all n8n flows identifying nodes that need conversion from direct table writes to either PGMQ job pushes or Supabase RPC calls. This keeps n8n as a thin orchestration layer while workers and RPCs own mutation logic.

## Conversion Principles

| Current Pattern                                      | Target Pattern                    | Why                                                         |
| ---------------------------------------------------- | --------------------------------- | ----------------------------------------------------------- |
| `n8n-nodes-base.supabase` UPDATE/INSERT on PII table | Supabase RPC via HTTP Request     | RPC enforces validation, audit, and RLS bypass in one place |
| Direct HTTP PATCH to `/rest/v1/<pii_table>`          | Supabase RPC via HTTP Request     | Same as above                                               |
| Business logic in n8n Code node → table write        | PGMQ job push + Python worker     | Workers own complex logic; n8n just schedules               |
| Notification/alert after failure                     | Keep as-is (queue_job notify_ops) | Already uses RPC pattern correctly                          |

---

## Flow-by-Flow Analysis

### 1. `dragonfly_new_lead_enrichment_v1`

**Trigger**: Cron (every 15 min)  
**Purpose**: Enrich new judgments with external data, then mark actionable

| Node                            | Current Action                      | Conversion Target                     | Status    |
| ------------------------------- | ----------------------------------- | ------------------------------------- | --------- |
| Fetch Leads                     | GET `/rest/v1/v_judgment_pipeline`  | ✅ Keep (view read)                   | OK        |
| Call OpenAI                     | External API call                   | ✅ Keep                               | OK        |
| **Insert Debtor Intelligence**  | POST `/rest/v1/debtor_intelligence` | ❌ → `rpc/upsert_debtor_intelligence` | NEEDS FIX |
| **Update Judgment: ACTIONABLE** | PATCH `/rest/v1/core_judgments`     | ❌ → `rpc/complete_enrichment`        | NEEDS FIX |
| Queue Alert                     | POST `rpc/queue_job`                | ✅ Keep                               | OK        |

**Required Changes**:

```
Old: POST /rest/v1/debtor_intelligence + PATCH /rest/v1/core_judgments
New: POST /rest/v1/rpc/complete_enrichment (handles both in transaction)
```

---

### 2. `dragonfly_enforcement_escalation_v1`

**Trigger**: Cron (daily)  
**Purpose**: Escalate stalled enforcement cases

| Node                       | Current Action                                       | Conversion Target                 | Status    |
| -------------------------- | ---------------------------------------------------- | --------------------------------- | --------- |
| Fetch Enforcement Cases    | GET `/rest/v1/v_enforcement_overview`                | ✅ Keep (view read)               | OK        |
| Flag Stalled Cases         | Code node (pure transform)                           | ✅ Keep                           | OK        |
| Call set_enforcement_stage | POST `rpc/set_enforcement_stage`                     | ✅ Keep (already RPC)             | OK        |
| **Touch Next Action**      | `n8n-nodes-base.supabase` UPDATE `enforcement_cases` | ❌ → `rpc/log_enforcement_action` | NEEDS FIX |
| Log Escalation Event       | POST `rpc/log_enforcement_event`                     | ✅ Keep (already RPC)             | OK        |
| Send Escalation Alert      | POST `rpc/queue_job`                                 | ✅ Keep                           | OK        |

**Required Changes**:

```
Old: Supabase node UPDATE enforcement_cases.next_action_at
New: POST /rest/v1/rpc/log_enforcement_action (sets next_action_at + logs event atomically)
```

---

### 3. `dragonfly_new_plaintiff_intake_v1`

**Trigger**: Cron (hourly)  
**Purpose**: Process new plaintiffs, queue intake enrichment jobs

| Node                        | Current Action                                | Conversion Target                             | Status    |
| --------------------------- | --------------------------------------------- | --------------------------------------------- | --------- |
| Fetch Intake Candidates     | GET `/rest/v1/plaintiffs`                     | ✅ Keep                                       | OK        |
| Prepare Intake Jobs         | Code node (pure transform)                    | ✅ Keep                                       | OK        |
| Queue Intake Job            | POST `rpc/queue_job`                          | ✅ Keep                                       | OK        |
| **Update Plaintiff Status** | `n8n-nodes-base.supabase` UPDATE `plaintiffs` | ❌ → `rpc/update_plaintiff_status`            | NEEDS FIX |
| **Record Intake Status**    | POST `/rest/v1/plaintiff_status_history`      | ❌ → Include in `rpc/update_plaintiff_status` | NEEDS FIX |
| Queue Failure Alert         | POST `rpc/queue_job`                          | ✅ Keep                                       | OK        |

**Required Changes**:

```
Old: Supabase node UPDATE plaintiffs + POST plaintiff_status_history
New: POST /rest/v1/rpc/update_plaintiff_status (updates status + writes history atomically)
```

**New RPC Needed**: `update_plaintiff_status(plaintiff_id uuid, new_status text, note text, changed_by text)`

---

### 4. `dragonfly_import_trigger_v1`

**Trigger**: Cron (hourly)  
**Purpose**: Seed import_runs and queue ETL dispatcher

| Node                       | Current Action                       | Conversion Target            | Status   |
| -------------------------- | ------------------------------------ | ---------------------------- | -------- |
| Fetch Ready Snapshot       | GET `/rest/v1/v_plaintiffs_overview` | ✅ Keep (view read)          | OK       |
| Summarize Pending Records  | Code node (pure transform)           | ✅ Keep                      | OK       |
| **Create Import Run**      | POST `/rest/v1/import_runs`          | ⚠️ → `rpc/create_import_run` | OPTIONAL |
| Queue Import Job           | POST `rpc/queue_job`                 | ✅ Keep                      | OK       |
| **Mark Import Run Queued** | PATCH `/rest/v1/import_runs`         | ⚠️ → Include in RPC          | OPTIONAL |
| Queue Failure Alert        | POST `rpc/queue_job`                 | ✅ Keep                      | OK       |

**Note**: `import_runs` is an internal workflow table, not PII. Direct writes are acceptable but RPC would improve atomicity.

---

### 5. `dragonfly_pgmq_consumer_v1`

**Trigger**: Cron (every 5 min)  
**Purpose**: Forward ready import_runs to pgmq_consume worker

| Node                    | Current Action               | Conversion Target             | Status   |
| ----------------------- | ---------------------------- | ----------------------------- | -------- |
| Fetch Ready Runs        | GET `/rest/v1/import_runs`   | ✅ Keep                       | OK       |
| Craft PGMQ Jobs         | Code node (pure transform)   | ✅ Keep                       | OK       |
| Queue PGMQ Job          | POST `rpc/queue_job`         | ✅ Keep                       | OK       |
| **Mark Run Processing** | PATCH `/rest/v1/import_runs` | ⚠️ → `rpc/advance_import_run` | OPTIONAL |
| Queue Failure Alert     | POST `rpc/queue_job`         | ✅ Keep                       | OK       |

---

### 6. `dragonfly_call_queue_sync_v1`

**Trigger**: Cron (every 15 min)  
**Purpose**: Sync call queue from v_plaintiff_call_queue

| Node             | Current Action                        | Conversion Target   | Status |
| ---------------- | ------------------------------------- | ------------------- | ------ |
| Fetch Call Queue | GET `/rest/v1/v_plaintiff_call_queue` | ✅ Keep (view read) | OK     |
| Queue sync job   | POST `rpc/queue_job`                  | ✅ Keep             | OK     |

**Status**: ✅ Already clean - no direct table writes

---

### 7. `dragonfly_call_task_planner_v1`

**Trigger**: Cron (nightly)  
**Purpose**: Plan call tasks for plaintiffs needing contact

| Node                         | Current Action                       | Conversion Target                | Status    |
| ---------------------------- | ------------------------------------ | -------------------------------- | --------- |
| Fetch Plaintiffs             | GET `/rest/v1/v_plaintiffs_overview` | ✅ Keep (view read)              | OK        |
| **Backfill plaintiff_tasks** | POST/PATCH `plaintiff_tasks`         | ❌ → `rpc/upsert_plaintiff_task` | NEEDS FIX |
| Queue planner job            | POST `rpc/queue_job`                 | ✅ Keep                          | OK        |

**New RPC Needed**: `upsert_plaintiff_task(plaintiff_id uuid, kind text, due_at timestamptz, metadata jsonb)`

---

### 8. `dragonfly_enforcement_timeline_updater_v1`

**Trigger**: Cron (daily)  
**Purpose**: Update enforcement timeline events

| Expected Pattern      | Target                                  |
| --------------------- | --------------------------------------- |
| Timeline event writes | Should use `rpc/log_enforcement_action` |

---

### 9. `dragonfly_evidence_bundler_v1`

**Trigger**: On-demand / scheduled  
**Purpose**: Bundle evidence documents

| Expected Pattern  | Target                       |
| ----------------- | ---------------------------- |
| Document assembly | PGMQ job → Python worker     |
| Status updates    | `rpc/update_judgment_status` |

---

### 10. `dragonfly_triage_alerts_v1`

**Trigger**: Cron  
**Purpose**: Alert on triage conditions

| Expected Pattern | Target                                    |
| ---------------- | ----------------------------------------- |
| Alert delivery   | ✅ Uses `rpc/queue_job` with `notify_ops` |

**Status**: ✅ Likely already clean

---

## Summary of Required Changes

### New RPCs Needed (add to 0205 migration)

| RPC Name                  | Parameters                                                         | Purpose                           |
| ------------------------- | ------------------------------------------------------------------ | --------------------------------- |
| `update_plaintiff_status` | `plaintiff_id uuid, new_status text, note text, changed_by text`   | Atomic status + history write     |
| `upsert_plaintiff_task`   | `plaintiff_id uuid, kind text, due_at timestamptz, metadata jsonb` | Atomic task upsert                |
| `advance_import_run`      | `import_run_id uuid, new_status text`                              | Optional: cleaner import workflow |

### n8n Node Conversions Required

| Flow                        | Node                        | From             | To                               |
| --------------------------- | --------------------------- | ---------------- | -------------------------------- |
| `new_lead_enrichment_v1`    | Insert Debtor Intelligence  | POST table       | `rpc/upsert_debtor_intelligence` |
| `new_lead_enrichment_v1`    | Update Judgment: ACTIONABLE | PATCH table      | `rpc/complete_enrichment`        |
| `enforcement_escalation_v1` | Touch Next Action           | Supabase node    | `rpc/log_enforcement_action`     |
| `new_plaintiff_intake_v1`   | Update Plaintiff Status     | Supabase node    | `rpc/update_plaintiff_status`    |
| `new_plaintiff_intake_v1`   | Record Intake Status        | POST table       | (merged into above RPC)          |
| `call_task_planner_v1`      | Backfill tasks              | POST/PATCH table | `rpc/upsert_plaintiff_task`      |

### Flows Already Using Correct Patterns ✅

- `dragonfly_call_queue_sync_v1` - pure view reads + queue_job
- `dragonfly_triage_alerts_v1` - pure alerts via queue_job
- Most flows correctly use `rpc/queue_job` for PGMQ pushes
- Most flows correctly use `rpc/set_enforcement_stage` and `rpc/log_enforcement_event`

---

## Implementation Checklist

- [ ] Create migration `0205_plaintiff_rpcs.sql` with `update_plaintiff_status`, `upsert_plaintiff_task`
- [ ] Update `dragonfly_new_lead_enrichment_v1.json`:
  - Replace "Insert Debtor Intelligence" with HTTP Request to `rpc/complete_enrichment`
  - Remove "Update Judgment: ACTIONABLE" node (merged into complete_enrichment)
- [ ] Update `dragonfly_enforcement_escalation_v1.json`:
  - Replace "Touch Next Action" Supabase node with HTTP Request to `rpc/log_enforcement_action`
- [ ] Update `dragonfly_new_plaintiff_intake_v1.json`:
  - Replace "Update Plaintiff Status" and "Record Intake Status" with single HTTP Request to `rpc/update_plaintiff_status`
- [ ] Update `dragonfly_call_task_planner_v1.json`:
  - Replace task backfill with HTTP Request to `rpc/upsert_plaintiff_task`
- [ ] Update `docs/worker_n8n_rpc_reference.md` with new RPCs
- [ ] Run `python -m tools.check_schema_consistency --env dev` after migration

---

## Architecture Goal

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────────┐
│    n8n       │     │   Supabase      │     │  Python Workers  │
│  (thin)      │     │   RPCs          │     │  (business logic)│
├──────────────┤     ├─────────────────┤     ├──────────────────┤
│ • Cron       │────▶│ • queue_job     │────▶│ • enrich handler │
│ • View reads │     │ • complete_*    │     │ • outreach handler│
│ • HTTP calls │     │ • update_*      │     │ • enforce handler │
│ • Alerts     │     │ • log_*         │     │                  │
└──────────────┘     └─────────────────┘     └──────────────────┘
        │                    │                       │
        │                    ▼                       │
        │           ┌───────────────┐                │
        └──────────▶│  PII Tables   │◀───────────────┘
                    │  (RLS FORCED) │
                    └───────────────┘
```

n8n **never** writes directly to PII tables. All mutations flow through RPCs which:

1. Validate inputs
2. Enforce business rules
3. Write audit trails
4. Execute in transactions
