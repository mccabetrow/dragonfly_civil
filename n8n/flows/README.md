# Dragonfly Ops Automation Bundle

> **Architecture Principle:** n8n is a thin notification/trigger layer. All business logic lives in Python workers + Supabase RPCs. See `docs/n8n_bridge_architecture.md` for the full migration guide.

## Flow Categories

### ✅ Notification-Only Flows (NEW v2 Architecture)

| Flow                       | Purpose                                 | Trigger             | Data Source                |
| -------------------------- | --------------------------------------- | ------------------- | -------------------------- |
| `new_lead_alert_v1.json`   | Discord alert when enrichment completes | Webhook from worker | Webhook payload            |
| `daily_ops_digest_v1.json` | Morning summary to Discord              | Cron 8:30 AM ET     | `/api/ops/digest` or views |

### ⚠️ Transitional Flows (Use RPCs, no direct writes)

| Flow                                       | Purpose                            | Trigger       | Primary RPCs                                             |
| ------------------------------------------ | ---------------------------------- | ------------- | -------------------------------------------------------- |
| `dragonfly_new_plaintiff_intake_v1.json`   | Queue intake enrichment jobs       | Cron – hourly | `rpc/queue_job`                                          |
| `dragonfly_open_tasks_monitor_v1.json`     | Flag overdue tasks, alert Slack    | Cron – 15 min | `rpc/queue_job`                                          |
| `dragonfly_enforcement_escalation_v1.json` | Escalate stalled cases             | Cron – daily  | `rpc/set_enforcement_stage`, `rpc/log_enforcement_event` |
| `dragonfly_call_queue_sync_v1.json`        | Sync call queue + fan out jobs     | Cron – 15 min | `rpc/queue_job`                                          |
| `dragonfly_triage_alerts_v1.json`          | Route triage alerts to Slack/email | Cron – 10 min | `rpc/ops_triage_alerts`, `rpc/queue_job`                 |
| `dragonfly_pgmq_monitor_v1.json`           | Monitor PGMQ depth/age             | Cron – 5 min  | `rpc/pgmq_metrics`, `rpc/queue_job`                      |

### ❌ Deprecated Flows (Business logic moved to workers)

| Flow                                    | Replacement                                           | Notes                                   |
| --------------------------------------- | ----------------------------------------------------- | --------------------------------------- |
| `dragonfly_new_lead_enrichment_v1.json` | `workers/enrich_worker.py` + `new_lead_alert_v1.json` | Enrichment in Python; n8n just notifies |

## v2 Architecture Patterns

### View Reads Only

```javascript
// ✅ CORRECT: Read from view, format, post to Discord
GET /rest/v1/v_enforcement_pipeline_status → Discord
```

### RPC Writes Only

```javascript
// ✅ CORRECT: All writes through RPCs
POST / rest / v1 / rpc / queue_job;
POST / rest / v1 / rpc / set_enforcement_stage;
POST / rest / v1 / rpc / log_enforcement_action;
```

### No Direct Table Writes

```javascript
// ❌ WRONG: Direct INSERT/UPDATE to tables
POST / rest / v1 / debtor_intelligence; // Migrate to RPC
PATCH / rest / v1 / plaintiffs; // Migrate to RPC
```

## Required Python API Endpoints

| Endpoint                                     | Purpose            | Used By                    |
| -------------------------------------------- | ------------------ | -------------------------- |
| `GET /api/ops/digest`                        | Daily summary data | `daily_ops_digest_v1.json` |
| `POST /api/ops/webhooks/enrichment-complete` | Trigger lead alert | `enrich_worker.py`         |

Six n8n workflows automate the CODex operations pack. Import each JSON file in this folder, update credentials (`Generic Credential`, `Supabase Service`), and enable the flows once the referenced RPCs exist in Supabase.

| Flow                                       | Purpose                                                                                                                              | Trigger             | Primary RPCs                                             |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------- | -------------------------------------------------------- |
| `dragonfly_new_plaintiff_intake_v1.json`   | Sweeps `v_plaintiffs_overview` for intake_pending records, queues `intake_enrich` jobs, and marks plaintiffs as `intake_processing`. | Cron – hourly       | `rpc/queue_job`                                          |
| `dragonfly_open_tasks_monitor_v1.json`     | Flags plaintiff tasks >60 minutes overdue, updates `plaintiff_tasks.escalation_state`, queues `ops_task_followup`, and alerts Slack. | Cron – every 15 min | `rpc/queue_job`                                          |
| `dragonfly_enforcement_escalation_v1.json` | Escalates cases stuck in a stage, calls `set_enforcement_stage`, logs enforcement events, and alerts on failure.                     | Cron – daily        | `rpc/set_enforcement_stage`, `rpc/log_enforcement_event` |
| `dragonfly_call_queue_sync_v1.json`        | Keeps the call queue + `plaintiff_tasks` in sync and fans work out through `call_queue_sync` jobs.                                   | Cron – every 15 min | `rpc/queue_job`                                          |
| `dragonfly_pgmq_monitor_v1.json`           | Watches PGMQ depth/age, stores snapshots in `ops_metadata`, and emits alerts when thresholds breach.                                 | Cron – every 5 min  | `rpc/pgmq_metrics`, `rpc/queue_job`                      |
| `dragonfly_triage_alerts_v1.json`          | Pulls `ops_triage_alerts`, routes severity high+ to Slack (else email), and acknowledges alert rows.                                 | Cron – every 10 min | `rpc/ops_triage_alerts`, `rpc/queue_job`                 |

## Node + error-handling patterns

- **HTTP Request nodes** handle all RPC + REST calls with `retryOnFail=true` and `maxAttempts=3`. Replace `<project-ref>` and `SUPABASE_SERVICE_ROLE_KEY` with environment variables or n8n credentials.
- **Supabase nodes** (insert/update) require the `Supabase Service` credential. They keep `plaintiffs`, `plaintiff_tasks`, `enforcement_cases`, `ops_metadata`, and `ops_triage_alerts` in sync with automation state.
- **Code nodes** replace deprecated Function nodes and encapsulate any payload shaping, severity logic, or RPC response normalization.
- **Set nodes** build explicit alert payloads so the same structure can be shared with Slack/email/webhook transports.
- **Wait nodes** stagger each cron trigger a few seconds to avoid fighting upstream refresh jobs.
- **IF nodes** gate failure handling. False branches always assemble a `notify_ops` payload so humans are alerted when queueing or RPC calls fail.

## Deployment checklist

1. **Credentials** – Create two n8n credentials: `Generic Credential` (HTTP header auth with the Supabase service key) and `Supabase Service` (API URL/key for the Supabase node). Update the placeholder IDs inside the JSON if your instance names differ.
2. **RPC availability** – Ensure the following RPCs are deployed: `queue_job`, `set_enforcement_stage`, `log_enforcement_event`, `pgmq_metrics`, `ops_triage_alerts`. Each flow assumes they live under `/rest/v1/rpc/<name>`.
3. **Tables/views** – Views `v_plaintiffs_overview`, `v_plaintiff_open_tasks`, `v_plaintiff_call_queue`, `v_enforcement_overview`, and tables `plaintiff_tasks`, `enforcement_cases`, `ops_metadata`, `ops_triage_alerts` must match schema expectations (columns referenced in the JSON).
4. **Alert routing** – The `notify_ops` queue job payloads include `channel` hints (`slack` or `email`). Confirm downstream workers respect those hints.
5. **Testing** – Import one workflow at a time, run it manually in n8n using sample data, then enable the cron trigger. Monitor `tools.ops_healthcheck` + `ops_daily_report` to confirm new automations do not double-write tasks.

## Failure + retry strategy

- Every RPC call uses `retryOnFail` with three attempts. If the RPC still fails, the workflow routes into the failure branch, builds a payload via the Set/Code nodes, and raises a `notify_ops` job with context (`plaintiff_id`, `case_id`, queue response, etc.).
- Supabase inserts/updates run before queuing where needed to avoid duplicate downstream effort. Because operations are idempotent (`idempotency_key`), re-running the flow is safe after an outage.
- Wait nodes keep cron starts staggered across the automation pack so Supabase RPC traffic is smooth even when n8n restarts.

These flows provide the requested ops automation bundle; adjust schedules or thresholds inside the JSON if your SUPABASE environment requires different SLAs.
