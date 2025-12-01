# Database & RPC Requirements for the Enforcement Engine

This document translates the tier + flow blueprint into concrete schema and API work. Favor incremental migrations on the canonical Supabase schema located under `supabase/migrations/` and expose functionality via RPCs so Ops Console, workers, and PowerShell tooling stay in sync.

## Schema Updates

### enforcement_cases (existing)

| Column                                                | Type                     | Purpose                                                                           |
| ----------------------------------------------------- | ------------------------ | --------------------------------------------------------------------------------- |
| `tier`                                                | `text` (`tier0`–`tier3`) | Current automated tier assignment.                                                |
| `tier_reason`                                         | `text`                   | Short rationale for latest tier (e.g., `score>80`, `override`).                   |
| `tier_as_of`                                          | `timestamptz`            | When tier was last recalculated.                                                  |
| `tier_override`                                       | `text` nullable          | Manual override tier.                                                             |
| `override_expires_at`                                 | `timestamptz`            | When override should expire.                                                      |
| `override_note`                                       | `text`                   | Why override exists.                                                              |
| `collectability_score`                                | `numeric(5,2)`           | Persist analytics output for auditing.                                            |
| `asset_flags`                                         | `jsonb`                  | `{ "bank": true, "employer": false, ... }` aggregated hints.                      |
| `levy_status`, `garnishment_status`, `marshal_status` | `text`                   | Track state machine per workflow.                                                 |
| `next_action_at`                                      | `timestamptz`            | When Ops Console should resurface the case.                                       |
| `current_stage`                                       | `text`                   | Mirror of canonical stage value (with check constraint referencing lookup table). |

Add partial index on `(current_stage, tier)` to speed dashboard queries.

### enforcement_events (existing)

- Add `event_kind` enum values: `asset_search_requested`, `asset_search_completed`, `bank_levy_filed`, `bank_levy_served`, `bank_levy_released`, `garnishment_order_signed`, `garnishment_served`, `garnishment_remittance`, `subpoena_issued`, `subpoena_complied`, `marshal_assigned`, `marshal_attempted`, `marshal_result`, `case_stage_changed`.
- Columns:
  - `document_path text` (Supabase storage key) – required for action stages.
  - `related_task_id uuid` – link back to plaintiff/enforcement tasks if event closes a task.
  - `payload jsonb` – structured data (bank name, serve date, etc.). Ensure default `{}`.

### enforcement_history (existing)

- Add `actor_type text` (`user`, `automation`, `rpc`).
- Add `delta jsonb` – diff summary (previous stage/tier vs new).

### enforcement_actions (new table)

Stores long-running action workflows (levy, garnishment, subpoena, marshal) with statuses.

```sql
create table public.enforcement_actions (
    id uuid primary key default gen_random_uuid(),
    enforcement_case_id uuid references public.enforcement_cases(id) on delete cascade,
    action_type text not null check (action_type in ('bank_levy','garnishment','subpoena','marshal')),
    status text not null,
    status_reason text,
    opened_at timestamptz not null default timezone('utc', now()),
    closed_at timestamptz,
    metadata jsonb not null default '{}',
    created_by text not null,
    updated_by text,
    updated_at timestamptz not null default timezone('utc', now())
);
create index on public.enforcement_actions (enforcement_case_id, action_type, status);
```

### enforcement_documents (new table)

Track filings & evidence referenced by workflows.

```sql
create table public.enforcement_documents (
    id uuid primary key default gen_random_uuid(),
    enforcement_case_id uuid references public.enforcement_cases(id) on delete cascade,
    event_id uuid references public.enforcement_events(id),
    doc_kind text not null,
    storage_path text not null,
    uploaded_by text not null,
    uploaded_at timestamptz not null default timezone('utc', now()),
    metadata jsonb not null default '{}'
);
```

### Lookup Tables / Enums

- `enforcement_stage_lookup(stage text primary key, ordinal int, description text)` – enables FK from `enforcement_cases.current_stage`.
- `enforcement_tier_lookup(tier text primary key, min_score numeric, max_score numeric)` – optional for analytics.

## RPC Requirements

### 1. `open_enforcement_case`

Creates a case tied to a judgment/plaintiff. Validates no open case already exists.

**Signature:**

```sql
create or replace function public.open_enforcement_case(payload jsonb)
returns uuid
```

**Payload fields:** `judgment_id`, `plaintiff_id`, `tier`, `collectability_score`, `created_by`, `notes`.
**Behavior:**

- Inserts into `enforcement_cases` with `current_stage = 'pre_enforcement'`.
- Logs `enforcement_history` row with `actor_type = 'rpc'`.
- Returns new case id.

### 2. `close_enforcement_case`

Marks case as satisfied/uncollectible.

Fields: `case_id`, `status` (`satisfied`, `uncollectible`, `withdrawn`), `note`, `closed_by`.

- Updates `enforcement_cases.closed_at`, `closure_reason`.
- Auto-closes open `enforcement_actions`.
- Writes `case_stage_changed` event to timeline.

### 3. `set_enforcement_stage`

Already referenced in Ops Console. Extend to enforce transitions + record timeline.

Fields: `case_id`, `stage`, `actor`, `note`, `metadata`.

- Validate stage ordinal >= current (unless `override=true`).
- Update `current_stage`, `next_action_at` default (stage-specific SLA), `enforcement_history` delta, `enforcement_events` entry.

### 4. `log_enforcement_event`

Generic event writer used by flows + automations.

Fields: `case_id`, `event_kind`, `payload`, `document_path`, `related_task_id`, `actor`.

- Inserts into `enforcement_events`.
- Optionally updates derived columns (e.g., `levy_status`).

### 5. `queue_enforcement_action`

Creates or updates `enforcement_actions` row.

Fields: `case_id`, `action_type`, `status`, `metadata`, `actor`.

- Upsert semantics keyed on `(case_id, action_type, status in active set)`.
- When status transitions to `completed` or `cancelled`, close the action and emit event.

### 6. `record_enforcement_payment`

Bridges enforcement events with finance. Not strictly part of flows but needed for Stage 5.

Fields: `case_id`, `judgment_id`, `amount`, `received_at`, `source`, `document_path`.

- Inserts `enforcement_events` with `event_kind = 'payment_received'`.
- Updates `judgments.balance_due`, `enforcement_cases.current_balance` (transactionally).

### 7. `issue_subpoena` / `record_subpoena_response`

Can be modeled as specialized wrappers around `queue_enforcement_action`, but dedicated RPCs keep logic simple for Ops.

- `issue_subpoena(payload jsonb)` writes to actions + events, uploads doc metadata.
- `record_subpoena_response(payload jsonb)` updates action + tasks, schedules review.

### 8. `queue_job`

- **Signature:** `queue_job(payload jsonb) returns bigint`
- **Purpose:** Internal producer that fans jobs out to PGMQ queues for enrich, outreach, enforce, and case_copilot workers.
- **Validation:** Requires `kind` (one of `enrich|outreach|enforce|case_copilot`) and an `idempotency_key`; rejects missing/empty values before writing to the queue.
- **Security:** Available to anon/authenticated/service_role so Ops Console buttons and service workers share the same pathway.

### 9. `request_case_copilot`

- **Signature:** `request_case_copilot(case_id uuid, requested_by text default null) returns bigint`
- **Purpose:** Convenience RPC that verifies the case exists, packages metadata, and enqueues a `case_copilot` job via `queue_job`.
- **Behavior:** Raises if the case is missing, otherwise builds a payload with `case_id`, `case_number`, `requested_by`, and `requested_at`, then returns the queue message id.
- **Security:** Same grant surface as `queue_job`, but the downstream `v_case_copilot_latest` view is now restricted to `service_role` to keep Copilot output internal-only.

### 10. `log_call_outcome`

- **Signature:** `log_call_outcome(plaintiff_id uuid, task_id uuid, outcome text, interest text, notes text, follow_up_at timestamptz) returns jsonb`
- **Purpose:** Single RPC for the call task flow—records a call attempt, closes the current task, updates plaintiff status history, and optionally schedules a follow-up task.
- **Behavior:** Normalizes `outcome` into status buckets (`do_not_call`, `bad_number`, `reached_hot`, etc.), writes to `plaintiff_call_attempts`, closes the originating task with metadata, writes to `plaintiff_status_history`, and when the outcome is not terminal plus a follow-up time is provided, creates another `plaintiff_tasks` row while returning a structured JSON payload summarizing what was done.
- **Security:** Available to anon/authenticated/service_role so Ops Console buttons can capture outcomes, but any downstream analytics views that include sensitive commentary must stay `service_role` scoped.

### Supporting RPCs Already In Production

Dragonfly’s intake + enforcement services depend on several maintenance RPCs. Keep them callable and documented so schema guard treats them as first-class objects:

- `set_case_enrichment(p_case_id uuid, p_collectability_score numeric, p_collectability_tier text, p_summary text default null)` – Updates `judgments.cases` with the latest collectability score/tier produced by enrichment, stamps `last_enriched_at`, and is callable by the service role only.
- `set_case_scores(p_case_id uuid, p_identity_score numeric, p_contactability_score numeric, p_asset_score numeric, p_recency_amount_score numeric, p_adverse_penalty numeric, p_collectability_score numeric, p_collectability_tier text)` – Persists the full scoring breakdown + derived tier back to `judgments.cases` (and `last_scored_at`) so dashboards, Copilot, and planners read identical numbers; service role only.
- `upsert_enrichment_bundle(bundle jsonb)` – Validates the case id, then merges contact and asset arrays into `enrichment.contacts` / `enrichment.assets` using upserts so vendor payloads stay normalized; returns counts for observability and is exposed to the service role only.
- `insert_or_get_entity(payload jsonb)` – Ensures entity/person rows exist exactly once while linking plaintiffs/judgments to normalized entity ids.
- `process_simplicity_imports(import_run_id uuid)` – Batch RPC that materializes Simplicity vendor exports into canonical plaintiffs/judgments rows under transactional guardrails.

### Retired RPCs (Documented For Posterity)

The following RPCs previously appeared in the schema freeze but have been superseded. They remain documented so future audits understand why they are no longer tracked:

- `ack_job(queue_name text, msg_id bigint)` – Workers now acknowledge PGMQ messages via the standard `pgmq_delete` RPC, so this bespoke wrapper is no longer deployed.
- `complete_plaintiff_call_task(task_id uuid, actor text, payload jsonb)` – The call-task workflow consolidated onto `log_call_outcome`, making this helper redundant.
- `set_updated_at()` – Modern triggers (`tg_touch_updated_at`, `judgments._set_updated_at`) keep timestamps in sync without exposing a public RPC.

## Derived Views

Update `v_enforcement_overview` and `v_enforcement_recent` to include:

- `tier`, `current_stage`, `next_action_at`, `days_in_stage`.
- Aggregates: counts per tier/stage, sum of `current_balance` per tier, SLA breach counts.

Ensure `v_enforcement_timeline` unions history + events + tasks + actions for chronological context.

### Priority Pipeline View

- Maintain `public.v_priority_pipeline` as the single ranked source for Ops Console, Case Copilot, and CLI tooling.
- Columns: `plaintiff_name`, `judgment_id`, `collectability_tier`, `priority_level`, `judgment_amount`, `county`, `state`, `stage`, `plaintiff_status`, `tier_rank`.
- Ordering: partition by `collectability_tier`, then sort by normalized `priority_level` (urgent→high→normal→low→on_hold) and descending `judgment_amount` so that dashboards and scripts can simply `select` + `order` without duplicating ranking logic.
- Dependencies: joins `public.judgments`, `public.plaintiffs`, `judgments.cases`, and `public.v_collectability_snapshot`; keep these joins lightweight and indexed to preserve dashboard load times.

## Automation Hooks

- Nightly job `public.refresh_enforcement_metrics()` recalculates tiers, next actions, days-in-stage.
- Worker listens for `NOTIFY enforcement_events_channel` triggered by `log_enforcement_event` to fan out alerts (email, Slack, queue jobs).

## Security & RLS

- Extend RLS policies so Ops users assigned to `role = 'enforcement_operator'` can call the above RPCs.
- Ensure `enforcement_documents` inherits same tenant access rules as parent case.
