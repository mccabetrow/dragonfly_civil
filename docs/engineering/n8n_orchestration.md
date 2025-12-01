# n8n Orchestration Blueprint

## Overview

This document defines the narrow HTTP surface that n8n uses to orchestrate Dragonfly Civil workflows. The FastAPI service (`src/api/app.py`) accepts API-key authenticated requests from n8n and persists them in Supabase using the service-role key. Every endpoint limits logic to validation, normalization, and the minimum database writes required for downstream dashboards.

> **Important:** n8n should be treated as a thin orchestration layer. Business logic belongs in Python workers; mutations should flow through Supabase RPCs. See `docs/n8n_bridge_mapping.md` for the full node-to-RPC conversion guide.

## Related Documentation

- `docs/worker_n8n_rpc_reference.md` - RPC function signatures and usage
- `docs/n8n_bridge_mapping.md` - Node-by-node conversion analysis
- `supabase/migrations/0204_unified_worker_rpcs.sql` - Core judgment RPCs
- `supabase/migrations/0205_plaintiff_rpcs.sql` - Plaintiff management RPCs

## Operations Snapshot (Mom & Dad)

- **Call Queue Sync (every 15 minutes)**: pulls `v_plaintiff_call_queue`, makes sure each plaintiff has an open `plaintiff_tasks` row, and enqueues `queue_job(kind='call_queue_sync')` work. If Supabase rejects the job or `log_call_outcome` fails, the flow immediately publishes `queue_job(kind='notify_ops', idempotency_key='call_sync_alert:<task_id>')` so ops sees the plaintiff/task that needs help.
- **Call Task Planner (nightly)**: scans `v_plaintiffs_overview` for statuses `contact_needed` / `contact_attempted`, builds a ranked list, backfills `plaintiff_tasks` (kind `call`), then enqueues `queue_job(kind='call_task_planner')` per plaintiff. Any RPC failure triggers `notify_ops` with the plaintiff id and RPC error payload so the roster can be re-run manually.
- **Enforcement Escalation (daily)**: reads `v_enforcement_overview` for stalled cases, calls `set_enforcement_stage`, touches `enforcement_cases.next_action_at`, and logs a timeline entry via `log_enforcement_event`. Both RPC hops are wrapped in alerting: if either fails, a `notify_ops` job is queued with `enforcement_case_id` and the raw Supabase response so ops can escalate manually.

Each workflow clearly states its guardrails inside the sticky-note node in n8n. When an alert hits `notify_ops` the on-call should search for the supplied `idempotency_key` or plaintiff/case id in Supabase to decide whether to retry or escalate.

## Authentication and Environment Routing

- Include `X-API-Key: <secret>` on every request. The secret is configured through `N8N_API_KEY` in `.env` and validated with a constant-time compare.
- Optional environment override: `X-Dragonfly-Env: dev` or `prod`. When omitted the service uses the default `SUPABASE_MODE` from runtime settings.
- Requests and responses use `application/json`. All payloads are idempotent on `case_number` or `task_id` to simplify retries from n8n.

## Endpoint Summary

| Method | Path                    | Purpose                                               | Primary Supabase write                                           |
| ------ | ----------------------- | ----------------------------------------------------- | ---------------------------------------------------------------- |
| POST   | `/api/cases`            | Upsert or create a case with core parties             | RPC `insert_or_get_case_with_entities`                           |
| POST   | `/api/outreach-events`  | Record an outbound communication touch                | `public.outreach_log` insert                                     |
| POST   | `/api/webhooks/inbound` | Capture inbound replies and optionally advance status | `public.outreach_log` insert, `judgments.cases` status update    |
| POST   | `/api/tasks/complete`   | Mark an enforcement task finished and capture notes   | `enforcement.tasks` update (+ log note in `public.outreach_log`) |

---

## POST /api/cases

Idempotently creates or updates a case and its key parties.

**Request body**

```json
{
  "case_number": "NYC-2024-0001",
  "source": "n8n_orchestrator",
  "title": "Plaintiff LLC v. Debtor",
  "court": "NYC Civil Court",
  "judgment_amount_cents": 150000,
  "metadata": {
    "workflow_run_id": "wf-123",
    "lead_source": "portal"
  },
  "plaintiff": {
    "name": "Plaintiff LLC",
    "is_business": true,
    "emails": ["ops@plaintiff.example"],
    "phones": ["+12125551234"]
  },
  "defendants": [
    {
      "name": "Debtor Person",
      "phones": ["+17185550000"],
      "metadata": {
        "address_on_file": "123 Example Ave"
      }
    }
  ]
}
```

**Response body**

```json
{
  "case_id": "7f7c1a4a-9f49-4a56-9a5d-3f8b5b6c6d54",
  "case_number": "NYC-2024-0001",
  "entity_ids": [
    "8f0de4d0-09c1-4c36-8b8d-bc2436611c1e",
    "7a854c4d-1b8a-43f3-a8ce-769953d0c9c0"
  ],
  "supabase_env": "prod"
}
```

**Notes**

- Validation requires at least one defendant. Phone numbers are normalized by trimming whitespace only.
- The handler runs `insert_or_get_case_with_entities` and echoes the case identifiers that Supabase returns.

---

## POST /api/outreach-events

Logs an outbound communication touch so dashboards and SLA monitors stay in sync.

**Request body**

```json
{
  "case_number": "NYC-2024-0001",
  "channel": "sms",
  "template": "payment_plan_intro_v1",
  "status": "sent",
  "recipient": "+17185550000",
  "sent_at": "2025-11-16T14:05:00Z",
  "metadata": {
    "n8n_execution_id": "480afa43-d6d6-4d88-a26d-cdc8e0bbf1f2"
  }
}
```

**Response body**

```json
{
  "id": 4281,
  "status": "sent"
}
```

**Notes**

- Persists a single row in `public.outreach_log` with merged metadata.
- `sent_at` is stored inside the metadata block when provided.

---

## POST /api/webhooks/inbound

Captures inbound replies (SMS, email, voice) and can advance the case state when n8n determines the next status.

**Request body**

```json
{
  "case_number": "NYC-2024-0001",
  "channel": "sms",
  "message": "Payment made. Please confirm.",
  "sender": "+17185550000",
  "received_at": "2025-11-16T18:42:17Z",
  "metadata": {
    "twilio_message_sid": "SM1234567890"
  },
  "next_case_status": "awaiting_payment_verification"
}
```

**Response body**

```json
{
  "id": 5932,
  "case_status_updated": true
}
```

**Notes**

- Inserts the inbound payload into `public.outreach_log` with `channel` set to `<channel>_inbound` and `status` set to `received`.
- When `next_case_status` is supplied the handler issues an `UPDATE` on `judgments.cases` to keep the pipeline in sync.

---

## POST /api/tasks/complete

Marks an enforcement task complete and optionally stores operator notes.

**Request body**

```json
{
  "task_id": "c0fb62ae-62b0-4ec7-9c43-3f0c11b8f61c",
  "status": "completed",
  "case_number": "NYC-2024-0001",
  "notes": "Documents mailed certified #940011189922394823"
}
```

**Response body**

```json
{
  "task_id": "c0fb62ae-62b0-4ec7-9c43-3f0c11b8f61c",
  "status": "completed"
}
```

**Notes**

- Updates `enforcement.tasks` (service role scope) to the supplied status.
- When notes are provided the service appends a lightweight entry to `public.outreach_log` (`channel = "task"`, `template = "completion_note"`) so the activity feed remains chronological.

---

## Workflow Examples

### 1. New Case Onboarding (Plaintiff Intake)

1. n8n receives a submission from the intake form.
2. n8n normalizes contacts, then calls `POST /api/cases` with the plaintiff and defendant payload.
3. On success n8n enqueues enrichment by publishing to Supabase queue (existing `queue_job` RPC).
4. n8n writes an activity note via `POST /api/outreach-events` to capture the welcome email/SMS it triggered.

### 2. Scheduled Status Digest (Plaintiff Updates)

1. Nightly n8n job aggregates open cases and their outreach log history.
2. For each plaintiff that needs an update, n8n composes a summary message and sends email via provider.
3. After the send step, n8n calls `POST /api/outreach-events` to log the digest (`template = "status_digest_v1"`) together with the `sent_at` timestamp.
4. Optionally, if the digest reveals a case ready for the next step, n8n may call `POST /api/tasks/complete` for the associated enforcement task.

### 3. Escalation for Stalled Statuses

1. A monitoring workflow queries `public.outreach_log`/`judgments.cases` via Supabase REST to find cases stuck in `outreach_stubbed` for >5 days.
2. For each case, n8n posts an escalation SMS/email through the outreach provider.
3. The workflow records the escalation touch with `POST /api/outreach-events` (`template = "outreach_escalation_v1"`).
4. When the defendant replies (through a webhook) n8n forwards the payload to `POST /api/webhooks/inbound` with `next_case_status = "awaiting_callback"` to unblock the team queue.

---

## Implementation Notes

- FastAPI application lives in `src/api/app.py` and is exported as `api.app` for deployment (e.g., `uvicorn src.api.app:app`).
- Supabase operations use the shared service-role client with LRU caching per environment to avoid re-authentication overhead.
- Input validation relies on Pydantic v2; all optional metadata fields accept arbitrary JSON objects but are compacted to remove `null` entries before insert.
- Any failures writing to Supabase return 5xx errors so n8n can retry or route to manual intervention.
