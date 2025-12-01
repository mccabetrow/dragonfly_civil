# Enforcement Stages & Workflows

This blueprint aligns judgment lifecycle actions to the existing enforcement tables (`enforcement_cases`, `enforcement_events`, `enforcement_history`, `v_enforcement_overview`, `v_enforcement_recent`, `v_enforcement_timeline`). Every enforcement case must sit in exactly one stage, and stage changes must emit an event + history row.

## Stage Framework

| Stage                             | Definition                                                                 | Trigger to Enter                                                   | Required Data Points                                                                                   | Trigger to Exit                                                  |
| --------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| 0. Intake / Pre-Enforcement       | Case validated, paperwork complete, waiting on first enforcement decision. | Import or manual creation; tier calculation complete.              | Plaintiff authorization, judgment balance, debtor profile, tier, `collectability_score`.               | Asset lead identified **or** outbound contact completed.         |
| 1. Contact & Validation           | Outreach to debtor / counsel to confirm assets and payment intent.         | Logged outbound contact event, assigned owner, next contact due.   | Primary contact coordinates, call outcome, dispute flags, compliance checklist.                        | Asset search kicked off **or** payment plan approved.            |
| 2. Asset Discovery                | Gathering evidence of bank accounts, employment, property, receivables.    | Asset search task started or vendor data ingested.                 | Asset search request ID, vendor reports stored, chain-of-custody metadata, confidence score per asset. | At least one actionable asset flagged, risk review complete.     |
| 3. Action Planning                | Determine remedy (levy, garnishment, subpoena, marshal).                   | Actionable asset + legal review sign-off.                          | Selected remedy, court requirements, cost estimate, plaintiff approval attached.                       | Filing submitted OR plan cancelled.                              |
| 4a. Bank Levy Execution           | Funds restraint via bank levy.                                             | Levy paperwork filed / served.                                     | Bank name, account suffix, marshal/constable assignment, serve date, return date.                      | Funds received, levy released, or quashed.                       |
| 4b. Wage Garnishment Execution    | Income withholding from employer.                                          | Garnishment order signed.                                          | Employer name, payroll contact, pay frequency, exemption limits, tracking of remittances.              | Garnishment satisfied, terminated, or converted to payment plan. |
| 4c. Subpoena / Information Demand | Compel disclosure of assets.                                               | Judge/clerk issues subpoena.                                       | Target entity, document list, serve date, compliance deadline, follow-up hearings.                     | Documents received, contempt filed, or subpoena withdrawn.       |
| 4d. Marshal / Sheriff Execution   | Physical levy / property seizure.                                          | Writ issued + marshal engaged.                                     | Property description, marshal name, scheduled execution window, insurance info.                        | Execution successful, rescheduled, or returned nulla bona.       |
| 5. Recovery Monitoring            | Funds flowing or in queue; ensure posting + plaintiff comms.               | First remittance logged.                                           | Payment schedule, suspense account reference, net-to-plaintiff calculations.                           | Judgment satisfied OR debtor defaults leading to new plan.       |
| 6. Closure / Recycle              | Judgment satisfied, discharged, or deemed uncollectible.                   | Case manager marks status or automation detects `balance_due = 0`. | Satisfaction filed, closure reason, notes for future reference.                                        | Optional recycle to Stage 1 if new intel arrives.                |

## Workflow Playbooks

### Asset Search Workflow

- **Required Documents:** Engagement letter, plaintiff authorization, skip-trace vendor package, affidavit of diligent search.
- **DB/Task Requirements:**
  - `enforcement_events` entries: `type = 'asset_search_requested'`, `asset_search_completed`, each storing vendor, request id, cost.
  - `enforcement_history` row when search completes with summary JSON (top assets, confidence).
  - Auto-create `plaintiff_tasks` (kind `asset_follow_up`) with due date 5 business days after results.
- **Relevant RPCs:** `log_enforcement_event(event_payload)` for request/completion; `set_enforcement_stage(case_id, 'asset_discovery')` triggered automatically.

### Bank Levy Workflow

- **Required Documents:** Levy application, supporting affidavit, writ, bank instructions, marshal cover letter.
- **DB/Task Requirements:**
  - `enforcement_cases` fields: `levy_status`, `levy_filed_at`, `levy_return_due`.
  - Events: `bank_levy_filed`, `bank_levy_served`, `bank_levy_released`, each with amount restrained, bank metadata.
  - Tasks: `marshal_follow_up`, `funds_posting_review` assigned to finance.
- **RPCs:** `open_enforcement_action(case_id, action_type='bank_levy', payload)` to track state machine; `record_levy_receipt(case_id, amount, received_at)`.

### Wage Garnishment Workflow

- **Required Documents:** Garnishment petition, court order, employer packet, payroll worksheet.
- **DB/Task Requirements:**
  - `enforcement_cases`: `garnishment_status`, `employer_contact_id`, `deduction_rate`, `next_pay_date`.
  - Events: `garnishment_order_signed`, `garnishment_served`, `remittance_received`.
  - Tasks: `employer_check_in`, `remittance_audit` recurring monthly.
- **RPCs:** `upsert_garnishment_schedule(case_id, schedule_payload)`, `close_garnishment(case_id, reason)`.

### Subpoena Workflow

- **Required Documents:** Subpoena template, proof of service, motion to compel, compliance log.
- **DB/Task Requirements:**
  - `enforcement_events`: `subpoena_issued`, `subpoena_complied`, `subpoena_contempt`.
  - Store `subpoena_target`, `due_date`, `documents_requested` JSON.
  - Tasks: `review_production`, `prep_contempt_motion`.
- **RPCs:** `issue_subpoena(case_id, target_payload)`, `record_subpoena_response(case_id, response_payload)`.

### Marshal / Sheriff Execution

- **Required Documents:** Writ of execution, property description, insurance binder, logistics schedule, marshal invoice.
- **DB/Task Requirements:**
  - `enforcement_cases`: `marshal_status`, `property_location`, `execution_window_start/end`.
  - Events: `marshal_assigned`, `marshal_attempted`, `marshal_result` with seizure outcome + sale date.
  - Tasks: `marshal_coordination`, `auction_follow_up`, `plaintiff_notification`.
- **RPCs:** `schedule_marshal_execution(case_id, marshal_payload)`, `record_marshal_result(case_id, result_payload)`.

## Flow Controls & Automation Hooks

1. **Stage Enforcement:** Use DB constraint or trigger so `enforcement_cases.stage` can only advance via RPC (`set_enforcement_stage`). Each RPC logs to `enforcement_history` and optionally writes to `enforcement_events` with `source = 'automation'`.
2. **Task SLA Monitoring:** nightly job reads `v_enforcement_recent` to find overdue tasks (stage-dependent) and reassign or escalate.
3. **Docs & Evidence Storage:** Store links (Supabase storage paths) on events; enforce `NOT NULL` for `document_path` on action stages (4a–4d).
4. **Timeline View:** `v_enforcement_timeline` should combine events + tasks per case for Ops Console; ensure new event types are documented here.
5. **Metrics:** `v_enforcement_overview` should expose counts per stage, average days-in-stage, and success rates per workflow to feed dashboard cards.
