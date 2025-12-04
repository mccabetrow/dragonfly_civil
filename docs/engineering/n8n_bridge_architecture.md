# n8n Bridge Architecture: Thin Orchestration Layer

> **Principle:** n8n is a notification and trigger layer only. All business logic lives in Python workers + Supabase RPCs.

> ⚠️ **WARNING:** Do not run migrations locally. Push SQL files to `supabase/migrations/` and let GitHub Actions handle it. See `.github/workflows/supabase-migrate.yml`.

## Current Flow Summary

| Flow                                        | Current State | Action                                        | Notes                                                     |
| ------------------------------------------- | ------------- | --------------------------------------------- | --------------------------------------------------------- |
| `dragonfly_new_lead_enrichment_v1`          | ❌ MIGRATE    | Replace with notification-only                | Enrichment logic → Python `enrich_worker.py`              |
| `dragonfly_enforcement_escalation_v1`       | ⚠️ PARTIAL    | Keep RPC calls, remove Supabase UPDATE        | Stage logic already via RPC; direct table write needs fix |
| `dragonfly_new_plaintiff_intake_v1`         | ⚠️ PARTIAL    | Keep queue_job, migrate status updates        | Status updates → `update_plaintiff_status` RPC            |
| `dragonfly_call_queue_sync_v1`              | ⚠️ PARTIAL    | Keep queue_job, migrate task inserts          | Task writes → `upsert_plaintiff_task` RPC                 |
| `dragonfly_call_task_planner_v1`            | ⚠️ PARTIAL    | Keep queue_job, migrate task backfill         | Task writes → `upsert_plaintiff_task` RPC                 |
| `dragonfly_intake_monitor_v1`               | ✅ KEEP       | Already uses queue_job only                   | Clean pattern                                             |
| `dragonfly_triage_alerts_v1`                | ✅ KEEP       | Pure notification routing                     | Clean pattern                                             |
| `dragonfly_pgmq_monitor_v1`                 | ✅ KEEP       | Pure monitoring                               | Clean pattern                                             |
| `dragonfly_import_trigger_v1`               | ✅ KEEP       | Queue job dispatch only                       | Clean pattern                                             |
| `dragonfly_pgmq_consumer_v1`                | ⚠️ OPTIONAL   | Migrate import_runs writes to RPC             | Low priority                                              |
| `dragonfly_enforcement_timeline_updater_v1` | ❌ MIGRATE    | Replace with worker                           | Timeline logic → Python worker                            |
| `dragonfly_evidence_bundler_v1`             | ❌ MIGRATE    | Replace with PGMQ job                         | Document assembly → Python worker                         |
| `dragonfly_foil_tracker_v1`                 | ⚠️ REVIEW     | Check for direct table writes                 | Needs audit                                               |
| `dragonfly_open_tasks_monitor_v1`           | ⚠️ PARTIAL    | Keep alerts, migrate escalation_state updates | Updates → RPC                                             |
| `csv_ingest_monitor`                        | ✅ KEEP       | Pure monitoring                               | Clean pattern                                             |
| `case_lifecycle_orchestrator`               | ⚠️ REVIEW     | Check for direct writes                       | Needs audit                                               |
| `ingestion_stub`                            | ✅ KEEP       | Testing stub                                  | N/A                                                       |

---

## Node Classification by Flow

### 1. `dragonfly_new_lead_enrichment_v1`

**Current:** Full enrichment pipeline in n8n (trigger → fetch → API call → AI transform → INSERT → UPDATE → notify)

| Node                                   | Classification | Action                                 |
| -------------------------------------- | -------------- | -------------------------------------- |
| `On New Unsatisfied Judgment`          | ❌ REMOVE      | Worker polling replaces trigger        |
| `Fetch Full Judgment`                  | ❌ REMOVE      | Worker handles                         |
| `Mock idiCORE Response`                | ❌ REMOVE      | Python worker calls idiCORE            |
| `Log FCRA Audit Trail`                 | ❌ REMOVE      | `log_external_data_call` RPC in worker |
| `AI: Transform to Intelligence Schema` | ❌ REMOVE      | Python handles transformation          |
| `Parse AI Response`                    | ❌ REMOVE      | Python handles                         |
| `Insert Debtor Intelligence`           | ❌ REMOVE      | → `complete_enrichment` RPC            |
| `Update Judgment: ACTIONABLE`          | ❌ REMOVE      | → `complete_enrichment` RPC            |
| `Discord: New Actionable Lead`         | ✅ KEEP        | Notification                           |

**New Flow:** Trigger on enrichment completion → Fetch summary → Discord alert

---

### 2. `dragonfly_enforcement_escalation_v1`

| Node                                      | Classification | Action                         |
| ----------------------------------------- | -------------- | ------------------------------ |
| `Daily Escalation Trigger`                | ✅ KEEP        | Cron                           |
| `Wait For Tier Refresh`                   | ✅ KEEP        | Timing                         |
| `Fetch Enforcement Cases`                 | ✅ KEEP        | View read                      |
| `Flag Stalled Cases`                      | ⚠️ MIGRATE     | Logic → Python worker          |
| `Build Stage Payload`                     | ⚠️ MIGRATE     | → Worker                       |
| `Call set_enforcement_stage`              | ✅ KEEP        | Already RPC                    |
| `Normalize Stage Response`                | ✅ KEEP        | Transform                      |
| `Stage RPC ok?`                           | ✅ KEEP        | Control flow                   |
| `UPDATE enforcement_cases.next_action_at` | ❌ MIGRATE     | → `log_enforcement_action` RPC |
| `Log Escalation Event`                    | ✅ KEEP        | Already RPC                    |
| `Queue notify_ops`                        | ✅ KEEP        | Alert                          |

**Recommended:** Move escalation logic to Python worker; n8n just triggers and notifies.

---

### 3. `dragonfly_call_queue_sync_v1`

| Node                            | Classification | Action                        |
| ------------------------------- | -------------- | ----------------------------- |
| `Call Queue Trigger`            | ✅ KEEP        | Cron                          |
| `Fetch Call Queue`              | ✅ KEEP        | View read                     |
| `Shape Call Queue`              | ⚠️ MIGRATE     | Logic → Python                |
| `Has Dialable Phone?`           | ⚠️ MIGRATE     | Logic → Python                |
| `POST plaintiff_tasks`          | ❌ MIGRATE     | → `upsert_plaintiff_task` RPC |
| `Queue call_queue_sync job`     | ✅ KEEP        | queue_job                     |
| `log_call_outcome (bad_number)` | ⚠️ CHECK       | Should be RPC                 |

**Recommended:** Keep as trigger/notify; task management → Python worker.

---

### 4. `dragonfly_new_plaintiff_intake_v1`

| Node                            | Classification | Action                          |
| ------------------------------- | -------------- | ------------------------------- |
| `Hourly Intake Trigger`         | ✅ KEEP        | Cron                            |
| `Fetch Intake Candidates`       | ✅ KEEP        | View read                       |
| `Prepare Intake Jobs`           | ✅ KEEP        | Transform                       |
| `Queue Intake Job`              | ✅ KEEP        | queue_job                       |
| `UPDATE plaintiffs.status`      | ❌ MIGRATE     | → `update_plaintiff_status` RPC |
| `POST plaintiff_status_history` | ❌ MIGRATE     | Merged into above RPC           |
| `Queue notify_ops`              | ✅ KEEP        | Alert                           |

---

## Required RPCs (Migration Targets)

| RPC Name                           | Parameters                                             | Purpose                                                     | Status        |
| ---------------------------------- | ------------------------------------------------------ | ----------------------------------------------------------- | ------------- |
| `complete_enrichment`              | `judgment_id, intelligence_data, collectability_score` | Atomic: insert debtor_intelligence + update judgment status | EXISTS        |
| `update_plaintiff_status`          | `plaintiff_id, new_status, note, changed_by`           | Atomic: update plaintiffs + write history                   | NEEDED        |
| `upsert_plaintiff_task`            | `plaintiff_id, kind, due_at, metadata`                 | Atomic: upsert task with idempotency                        | NEEDED        |
| `log_enforcement_action`           | `case_id, action_type, status, notes, next_action_at`  | Atomic: log action + update next_action_at                  | NEEDED        |
| `update_enforcement_action_status` | `action_id, new_status, notes`                         | Update action status (signature workflow)                   | EXISTS (0215) |
| `advance_import_run`               | `import_run_id, new_status`                            | Optional: cleaner import workflow                           | OPTIONAL      |

---

## New Python API Endpoints

### `/api/ops/digest`

Returns daily ops digest data for n8n to format and post to Discord.

```python
@app.get("/api/ops/digest")
async def get_ops_digest(
    api_key: None = Depends(require_api_key),
    x_env: Optional[str] = Header(None, alias=ENV_HEADER),
) -> OpsDigestResponse:
    """
    Returns:
    - pipeline_counts: dict of stage → count
    - pending_signatures: int
    - call_queue_top10: list of {plaintiff_name, tier, phone, due_at}
    - enforcement_stalled: int (cases >3 days in stage)
    """
```

### `/api/webhooks/enrichment-complete`

Webhook endpoint for workers to trigger n8n notification.

```python
@app.post("/api/webhooks/enrichment-complete")
async def enrichment_complete_webhook(
    payload: EnrichmentCompletePayload,
    api_key: None = Depends(require_api_key),
) -> dict:
    """
    Called by enrich_worker after successful enrichment.
    Triggers n8n notification flow via webhook or internal queue.
    """
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              THIN n8n LAYER                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ Daily Ops Digest │  │ New Lead Alert   │  │ Triage Alerts    │          │
│  │ (Cron 8:30 AM)   │  │ (Webhook trigger)│  │ (Cron 10 min)    │          │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘          │
│           │                     │                     │                    │
│           ▼                     ▼                     ▼                    │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │  HTTP Request to Python API  │  HTTP Request to Supabase RPC │          │
│  └────────┬─────────────────────┴────────────────────┬─────────┘          │
│           │                                          │                    │
│           ▼                                          ▼                    │
│  ┌──────────────────┐                      ┌──────────────────┐           │
│  │ Discord / Slack  │                      │ Email Transport  │           │
│  │ Notification     │                      │                  │           │
│  └──────────────────┘                      └──────────────────┘           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            PYTHON API LAYER                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ /api/ops/digest  │  │ /api/webhooks/*  │  │ /api/cases       │          │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘          │
└───────────┼─────────────────────┼─────────────────────┼─────────────────────┘
            │                     │                     │
            ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SUPABASE RPC LAYER                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ complete_        │  │ update_plaintiff_│  │ log_enforcement_ │          │
│  │ enrichment       │  │ status           │  │ action           │          │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘          │
└───────────┼─────────────────────┼─────────────────────┼─────────────────────┘
            │                     │                     │
            ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PYTHON WORKERS (Business Logic)                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ enrich_worker    │  │ call_queue_worker│  │ enforcement_     │          │
│  │ (idiCORE, AI)    │  │ (task planner)   │  │ escalation_worker│          │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
            │                     │                     │
            ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            SUPABASE TABLES                                  │
│  core_judgments │ debtor_intelligence │ plaintiffs │ enforcement_actions   │
│  plaintiff_tasks │ plaintiff_status_history │ enforcement_cases           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Migration Checklist

### Phase 1: New Notification-Only Flows

- [ ] Deploy `new_lead_alert_v1.json` (replaces enrichment notifications)
- [ ] Deploy `daily_ops_digest_v1.json` (new daily summary)
- [ ] Add `/api/ops/digest` endpoint to Python API

### Phase 2: Convert Direct Table Writes

- [ ] Create `update_plaintiff_status` RPC
- [ ] Create `upsert_plaintiff_task` RPC
- [ ] Create `log_enforcement_action` RPC (if not exists)
- [ ] Update `dragonfly_new_plaintiff_intake_v1` to use RPC
- [ ] Update `dragonfly_call_queue_sync_v1` to use RPC
- [ ] Update `dragonfly_enforcement_escalation_v1` to use RPC

### Phase 3: Retire Complex Flows

- [ ] Disable `dragonfly_new_lead_enrichment_v1` (after worker verified)
- [ ] Disable `dragonfly_enforcement_timeline_updater_v1` (after worker verified)
- [ ] Archive deprecated flow JSONs to `n8n/flows/_deprecated/`

### Phase 4: Cleanup

- [ ] Remove unused n8n credentials
- [ ] Update `n8n/flows/README.md` with new architecture
- [ ] Run `tools.doctor --env prod` to verify health
