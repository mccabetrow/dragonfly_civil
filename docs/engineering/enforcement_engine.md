# Dragonfly Enforcement Engine — Operator Manual

Audience: CEO / Lead Enforcement Officer (“Dad”). Goal: keep the enforcement system humming without diving into SQL. This guide summarizes how to read the dashboards, what to demand from the team weekly, and which levers exist in the database / RPC layer. Pair this with the tier specification (`enforcement_tiers.md`), flow diagrams (`enforcement_flows.md`), and schema plan (`database_rpc_requirements.md`).

## 1. Mental Model

1. Every judgment lives in an **enforcement case**.
2. Each case has two governing attributes:
   - **Tier** — priority/collectability (Tier 0–3).
   - **Stage** — where we are in the enforcement flow (intake → execution → recovery).
3. Workflows (asset search, levy, garnishment, subpoena, marshal) are just specialized action plans layered onto the case.
4. `enforcement_events` are the “black box recorder”: every decision, filing, and payment belongs here.
5. Ops Console surfaces the above via `v_enforcement_overview`, `v_enforcement_recent`, and timeline views; nothing should require ad hoc spreadsheets.

## 2. Daily Operating Rhythm

| Time             | Checklist                                                                                                                                                    |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Morning stand-up | Open Ops Console “Enforcement” view. Filter Tier 2/3 cases with past-due `next_action_at`. Assign owners, trigger RPCs to advance stage if blockers cleared. |
| Midday           | Review new `enforcement_events` (look at `v_enforcement_recent`). Make sure each levy/garnishment/subpoena has matching documents uploaded.                  |
| End of day       | Run `python -m tools.doctor --env dev` (or Prod) if schema was touched. Confirm new cases entered Stage 1 within 24h.                                        |

Red flags: Tier 3 cases sitting >7 days in same stage, action workflows without documents, payments logged without linking to cases.

## 3. Weekly Executive Review

1. **Tier roll-up** — from `v_enforcement_overview`, capture balance per tier and number of cases breaching SLA.
2. **Stage dwell time** — highlight bottlenecks (e.g., asset discovery taking >10 days). Ask owners for remediation plan.
3. **Workflow pipeline** — count of active levies, garnishments, subpoenas, marshal actions. Ensure each has next milestone scheduled.
4. **Recoveries vs projections** — compare `record_enforcement_payment` totals to plan; escalate gaps to finance.
5. **Quality audit** — randomly sample events to check doc links, notes, and use of standardized RPCs.

## 4. Running the Engine

- **Tier governance**: Nightly job assigns tiers automatically. If you need to override (e.g., VIP plaintiff), instruct ops to set `tier_override` via console or RPC. Overrides expire automatically; push for root causes if overrides persist.
- **Stage transitions**: Only move stages through `set_enforcement_stage`; this maintains history + triggers tasks. Ask “What RPC moved this case?” when investigating anomalies.
- **Action workflows**: Demand that each levy/garnishment/subpoena/marshal run through the corresponding RPC (`queue_enforcement_action`, `issue_subpoena`, etc.) so dashboards stay accurate.
- **Event hygiene**: No enforcement action is considered real unless it appears in `enforcement_events` with a document link. Make this a non-negotiable practice.
- **Metrics**: `v_enforcement_recent` powers the Ops Console side panel. Keep latency low by ensuring nightly refresh tasks run (see Make targets or VS Code tasks). If the view lags, run `scripts/bootstrap.ps1 -Mode reload`.

## 5. CEO Escalation Paths

- **Blockers**: If an external dependency (marshal, court) stalls, add an `enforcement_event` with `event_kind = 'blocked'`, include ETA, and set `next_action_at`. This ensures Ops Console reminders fire.
- **Policy changes**: Update tier criteria or stage definitions in the docs, then open a Supabase migration to adjust enums/lookups. Always re-run `db_push.ps1` in dev before prod.
- **Data corrections**: Use the importer helpers (`tools/run_import.py`) for bulk updates; never run ad-hoc SQL for plaintiffs/judgments.

## 6. When Things Break

1. **Views erroring**: Run `python -m tools.smoke_plaintiffs` and `python -m tools.doctor --env prod` to detect schema/view drift.
2. **RPC failures**: Check `logs/` or Supabase logs for `queue_job` errors. Use `_cleanup_queue_jobs` helper (tests reference) to requeue if needed.
3. **Docs missing**: Query `enforcement_documents` for NULL `storage_path`. Missing docs should be fixed within 1 business day.

## 7. Reference Stack

- Docs: `docs/enforcement_tiers.md`, `docs/enforcement_flows.md`, `docs/database_rpc_requirements.md`.
- Views consumed by dashboard: `v_enforcement_overview`, `v_enforcement_recent`, `v_enforcement_timeline`, `v_plaintiffs_overview`.
- Scripts: `scripts/db_push.ps1`, `scripts/preflight_dev.ps1`, `scripts/preflight_prod.ps1`.
- Tests: `tests/test_import_plaintiffs.py` (ensures queue + enforcement hooks intact when importers run).

Stay disciplined: if it isn’t written to the database via sanctioned RPCs, it didn’t happen. Keep tiers/stages accurate, document every action, and the engine will scale as fast as Dad wants.
