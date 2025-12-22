# Security Exceptions Documentation

> **Zero Trust Baseline**: All tables have RLS enabled and forced. All privileges revoked from `anon`, `authenticated`, and `public` roles. Access is granted ONLY through explicit RLS policies.

This document catalogues all SECURITY DEFINER functions in Dragonfly Civil. Each function must be documented here with justification before being added to the whitelist in `tests/test_security_audit_zero_trust.py`.

## Why SECURITY DEFINER?

SECURITY DEFINER functions execute with the privileges of the function **owner** (typically `postgres`), not the calling user. This is necessary when:

1. **Cross-role operations**: The function needs to access data the caller cannot
2. **Atomic transactions**: The function needs to update multiple tables atomically
3. **Audit logging**: The function needs to write audit records regardless of caller
4. **Queue operations**: The function needs to claim/update jobs without RLS interference

## Risk Mitigation

All SECURITY DEFINER functions in Dragonfly Civil:

- Are written with **explicit parameter validation**
- Do **not** execute dynamic SQL from user input
- Have **RLS forced** on underlying tables (prevents bypass even by owner)
- Are **audited** in automated tests (`tests/test_security_audit_zero_trust.py`)

---

## OPS Schema Functions

| Object Name                | Schema | Why SECURITY DEFINER                                                                    | Risks Mitigated                                   | Approved By         |
| -------------------------- | ------ | --------------------------------------------------------------------------------------- | ------------------------------------------------- | ------------------- |
| `claim_pending_job`        | ops    | Atomically claims jobs for workers. Must update job status regardless of caller's role. | Parameter validation, no dynamic SQL, idempotent. | Core Team - 2025-01 |
| `queue_job`                | ops    | Inserts jobs into queue. Must work from any authenticated context.                      | Parameter validation, schema-bound.               | Core Team - 2025-01 |
| `queue_job_idempotent`     | ops    | Idempotent job insertion. Prevents duplicate jobs.                                      | Idempotency key prevents abuse.                   | Core Team - 2025-03 |
| `enqueue_job`              | ops    | Alternative job insertion API.                                                          | Same as queue_job.                                | Core Team - 2025-03 |
| `reap_stuck_jobs`          | ops    | Recovers jobs stuck in processing. Runs on schedule.                                    | Only callable by service_role or scheduler.       | Core Team - 2025-06 |
| `complete_job`             | ops    | Marks job as completed. Must update regardless of caller.                               | Job ownership verified.                           | Core Team - 2025-01 |
| `fail_job`                 | ops    | Marks job as failed. Moves to DLQ if max attempts.                                      | Job ownership verified.                           | Core Team - 2025-01 |
| `update_job_status`        | ops    | Generic job status update.                                                              | Status enum validation.                           | Core Team - 2025-01 |
| `get_queue_health_summary` | ops    | Returns queue metrics. Read-only aggregation.                                           | No mutation, read-only.                           | Core Team - 2025-03 |
| `register_heartbeat`       | ops    | Records worker heartbeat. Must write to heartbeat table.                                | Worker ID validation.                             | Core Team - 2025-01 |
| `worker_heartbeat`         | ops    | Alternative heartbeat API.                                                              | Same as register_heartbeat.                       | Core Team - 2025-03 |
| `log_action`               | ops    | Writes audit log entry. Must work regardless of caller's permissions.                   | Immutable append-only table.                      | Core Team - 2025-01 |
| `log_audit`                | ops    | Alternative audit API.                                                                  | Same as log_action.                               | Core Team - 2025-03 |
| `log_intake_event`         | ops    | Logs intake pipeline events.                                                            | Append-only, no deletions.                        | Core Team - 2025-06 |
| `create_ingest_batch`      | ops    | Creates batch record for ingestion.                                                     | Batch ID is UUID, no collision.                   | Core Team - 2025-01 |
| `create_intake_batch`      | ops    | Alternative batch creation.                                                             | Same as create_ingest_batch.                      | Core Team - 2025-06 |
| `finalize_ingest_batch`    | ops    | Marks batch as complete with stats.                                                     | Batch ownership verified.                         | Core Team - 2025-01 |
| `finalize_intake_batch`    | ops    | Alternative batch finalization.                                                         | Same as finalize_ingest_batch.                    | Core Team - 2025-06 |
| `check_batch_integrity`    | ops    | Validates batch data integrity.                                                         | Read-only checks.                                 | Core Team - 2025-06 |
| `upsert_judgment`          | ops    | Upserts judgment record. Core data mutation.                                            | Conflict handling, idempotent.                    | Core Team - 2025-01 |
| `upsert_judgment_extended` | ops    | Extended judgment upsert with more fields.                                              | Same as upsert_judgment.                          | Core Team - 2025-03 |

---

## INTAKE Schema Functions

| Object Name                   | Schema | Why SECURITY DEFINER                   | Risks Mitigated                    | Approved By         |
| ----------------------------- | ------ | -------------------------------------- | ---------------------------------- | ------------------- |
| `create_foil_dataset`         | intake | Creates FOIL dataset record.           | UUID dataset ID, validated schema. | Core Team - 2025-09 |
| `finalize_foil_dataset`       | intake | Marks FOIL dataset as complete.        | Dataset ownership verified.        | Core Team - 2025-09 |
| `quarantine_foil_row`         | intake | Moves bad row to quarantine.           | Row ID validation.                 | Core Team - 2025-09 |
| `store_foil_raw_row`          | intake | Stores single raw FOIL row.            | Schema validation.                 | Core Team - 2025-09 |
| `store_foil_raw_rows_bulk`    | intake | Bulk stores raw FOIL rows.             | Batch validation, transaction.     | Core Team - 2025-09 |
| `update_foil_dataset_mapping` | intake | Updates column mapping.                | Dataset ownership verified.        | Core Team - 2025-09 |
| `update_foil_dataset_status`  | intake | Updates dataset status.                | Status enum validation.            | Core Team - 2025-09 |
| `update_foil_raw_row_status`  | intake | Updates row processing status.         | Row ID validation.                 | Core Team - 2025-09 |
| `process_raw_row`             | intake | Processes raw row into canonical form. | Validation pipeline.               | Core Team - 2025-09 |

---

## PUBLIC Schema Functions

### Access Control

| Object Name              | Schema | Why SECURITY DEFINER                            | Risks Mitigated          | Approved By         |
| ------------------------ | ------ | ----------------------------------------------- | ------------------------ | ------------------- |
| `dragonfly_can_read`     | public | Checks if current user can read a resource.     | Read-only role lookup.   | Core Team - 2025-01 |
| `dragonfly_has_any_role` | public | Checks if user has any of specified roles.      | Read-only role lookup.   | Core Team - 2025-01 |
| `dragonfly_has_role`     | public | Checks if user has specific role.               | Read-only role lookup.   | Core Team - 2025-01 |
| `dragonfly_is_admin`     | public | Checks if user is admin.                        | Read-only role lookup.   | Core Team - 2025-01 |
| `handle_new_user`        | public | Triggered on new user signup. Sets up defaults. | Trigger-only, validated. | Core Team - 2025-01 |

### Enforcement Operations

| Object Name                        | Schema | Why SECURITY DEFINER                    | Risks Mitigated                 | Approved By         |
| ---------------------------------- | ------ | --------------------------------------- | ------------------------------- | ------------------- |
| `add_enforcement_event`            | public | Adds event to enforcement timeline.     | Event type enum validation.     | Core Team - 2025-03 |
| `add_evidence`                     | public | Adds evidence record to case.           | Case ownership verified.        | Core Team - 2025-03 |
| `evaluate_enforcement_path`        | public | Calculates optimal enforcement path.    | Read-only computation.          | Core Team - 2025-06 |
| `generate_enforcement_tasks`       | public | Creates tasks for enforcement workflow. | Workflow ID validation.         | Core Team - 2025-06 |
| `get_enforcement_timeline`         | public | Returns enforcement history.            | Read-only, case access check.   | Core Team - 2025-03 |
| `log_enforcement_action`           | public | Logs enforcement action taken.          | Append-only audit.              | Core Team - 2025-03 |
| `log_enforcement_event`            | public | Alternative event logging.              | Same as log_enforcement_action. | Core Team - 2025-06 |
| `set_enforcement_stage`            | public | Updates enforcement stage.              | Stage enum validation.          | Core Team - 2025-03 |
| `spawn_enforcement_flow`           | public | Initiates enforcement workflow.         | Workflow validation.            | Core Team - 2025-06 |
| `update_enforcement_action_status` | public | Updates action status.                  | Action ownership verified.      | Core Team - 2025-06 |

### Case & Judgment Operations

| Object Name                        | Schema | Why SECURITY DEFINER                 | Risks Mitigated                 | Approved By         |
| ---------------------------------- | ------ | ------------------------------------ | ------------------------------- | ------------------- |
| `insert_case`                      | public | Inserts new case record.             | Duplicate detection.            | Core Team - 2025-01 |
| `insert_case_with_entities`        | public | Inserts case with related entities.  | Transaction, rollback on error. | Core Team - 2025-01 |
| `insert_entity`                    | public | Inserts entity (person/company).     | Deduplication logic.            | Core Team - 2025-01 |
| `insert_or_get_case`               | public | Idempotent case insertion.           | Conflict handling.              | Core Team - 2025-03 |
| `insert_or_get_case_with_entities` | public | Idempotent case+entities.            | Transaction, idempotent.        | Core Team - 2025-03 |
| `insert_or_get_entity`             | public | Idempotent entity insertion.         | Deduplication logic.            | Core Team - 2025-03 |
| `copilot_case_context`             | public | Returns case context for AI copilot. | Read-only, access check.        | Core Team - 2025-09 |
| `request_case_copilot`             | public | Queues copilot request.              | Rate limiting.                  | Core Team - 2025-09 |
| `update_judgment_status`           | public | Updates judgment status.             | Status enum validation.         | Core Team - 2025-01 |
| `set_judgment_priority`            | public | Sets judgment priority score.        | Score range validation.         | Core Team - 2025-03 |
| `score_case_collectability`        | public | Calculates collectability score.     | Read-only computation.          | Core Team - 2025-06 |
| `set_case_scores`                  | public | Updates case scoring fields.         | Score range validation.         | Core Team - 2025-06 |
| `portfolio_judgments_paginated`    | public | Returns paginated judgment list.     | Pagination limits enforced.     | Core Team - 2025-06 |
| `ops_update_judgment`              | public | Ops dashboard judgment update.       | Field validation.               | Core Team - 2025-06 |

### Plaintiff Operations

| Object Name                   | Schema | Why SECURITY DEFINER            | Risks Mitigated               | Approved By         |
| ----------------------------- | ------ | ------------------------------- | ----------------------------- | ------------------- |
| `set_plaintiff_status`        | public | Updates plaintiff status.       | Status enum validation.       | Core Team - 2025-06 |
| `update_plaintiff_status`     | public | Alternative status update.      | Same as set_plaintiff_status. | Core Team - 2025-06 |
| `ops_update_plaintiff_status` | public | Ops dashboard status update.    | Same as set_plaintiff_status. | Core Team - 2025-06 |
| `complete_plaintiff_task`     | public | Marks task as complete.         | Task ownership verified.      | Core Team - 2025-06 |
| `upsert_plaintiff_task`       | public | Creates/updates plaintiff task. | Task validation.              | Core Team - 2025-06 |
| `ops_update_task`             | public | Ops dashboard task update.      | Task validation.              | Core Team - 2025-06 |
| `log_call_outcome`            | public | Logs call attempt result.       | Append-only audit.            | Core Team - 2025-06 |
| `outreach_log_call`           | public | Alternative call logging.       | Same as log_call_outcome.     | Core Team - 2025-06 |
| `outreach_update_status`      | public | Updates outreach status.        | Status enum validation.       | Core Team - 2025-06 |

### Enrichment Operations

| Object Name                  | Schema | Why SECURITY DEFINER          | Risks Mitigated                | Approved By         |
| ---------------------------- | ------ | ----------------------------- | ------------------------------ | ------------------- |
| `complete_enrichment`        | public | Marks enrichment as complete. | Enrichment ownership verified. | Core Team - 2025-03 |
| `set_case_enrichment`        | public | Sets case enrichment data.    | Field validation.              | Core Team - 2025-03 |
| `upsert_enrichment_bundle`   | public | Upserts enrichment bundle.    | Idempotent, validated.         | Core Team - 2025-06 |
| `upsert_debtor_intelligence` | public | Upserts debtor intel record.  | Idempotent, validated.         | Core Team - 2025-06 |
| `enrichment_log_run`         | public | Logs enrichment run.          | Append-only audit.             | Core Team - 2025-06 |
| `enrichment_update_debtor`   | public | Updates debtor record.        | Field validation.              | Core Team - 2025-06 |

### Import Operations

| Object Name               | Schema | Why SECURITY DEFINER             | Risks Mitigated             | Approved By         |
| ------------------------- | ------ | -------------------------------- | --------------------------- | ------------------- |
| `advance_import_run`      | public | Advances import run state.       | State machine validation.   | Core Team - 2025-06 |
| `check_import_guardrails` | public | Validates import against limits. | Read-only checks.           | Core Team - 2025-06 |
| `store_intake_validation` | public | Stores validation results.       | Append-only.                | Core Team - 2025-06 |
| `submit_intake_review`    | public | Submits intake for review.       | State machine validation.   | Core Team - 2025-06 |
| `get_intake_stats`        | public | Returns intake statistics.       | Read-only aggregation.      | Core Team - 2025-06 |
| `fetch_new_candidates`    | public | Fetches unprocessed candidates.  | Pagination limits enforced. | Core Team - 2025-06 |

### Metrics & Dashboards

| Object Name                    | Schema | Why SECURITY DEFINER           | Risks Mitigated               | Approved By         |
| ------------------------------ | ------ | ------------------------------ | ----------------------------- | ------------------- |
| `ceo_12_metrics`               | public | Returns CEO dashboard metrics. | Read-only aggregation.        | Core Team - 2025-09 |
| `ceo_command_center_metrics`   | public | Returns command center data.   | Read-only aggregation.        | Core Team - 2025-09 |
| `enforcement_activity_metrics` | public | Returns enforcement metrics.   | Read-only aggregation.        | Core Team - 2025-06 |
| `enforcement_radar_filtered`   | public | Returns filtered radar data.   | Read-only, filter validation. | Core Team - 2025-06 |
| `intake_radar_metrics`         | public | Returns intake radar data.     | Read-only aggregation.        | Core Team - 2025-06 |
| `intake_radar_metrics_v2`      | public | Returns intake radar v2.       | Read-only aggregation.        | Core Team - 2025-09 |
| `compute_litigation_budget`    | public | Calculates litigation budget.  | Read-only computation.        | Core Team - 2025-06 |
| `get_litigation_budget`        | public | Returns current budget.        | Read-only.                    | Core Team - 2025-06 |
| `approve_daily_budget`         | public | Approves daily spend budget.   | Approval workflow.            | Core Team - 2025-06 |

### Logging Operations

| Object Name              | Schema | Why SECURITY DEFINER          | Risks Mitigated                | Approved By         |
| ------------------------ | ------ | ----------------------------- | ------------------------------ | ------------------- |
| `log_access`             | public | Logs access event.            | Append-only audit.             | Core Team - 2025-01 |
| `get_access_logs`        | public | Returns access logs.          | Read-only, pagination.         | Core Team - 2025-01 |
| `log_event`              | public | Generic event logging.        | Append-only audit.             | Core Team - 2025-01 |
| `log_export`             | public | Logs data export.             | Append-only audit.             | Core Team - 2025-03 |
| `log_external_data_call` | public | Logs external API call.       | Append-only audit.             | Core Team - 2025-06 |
| `log_insert_case`        | public | Logs case insertion.          | Append-only audit.             | Core Team - 2025-01 |
| `log_insert_entity`      | public | Logs entity insertion.        | Append-only audit.             | Core Team - 2025-01 |
| `log_sensitive_update`   | public | Logs sensitive field update.  | Append-only audit.             | Core Team - 2025-03 |
| `block_sensitive_delete` | public | Prevents sensitive deletions. | Raises exception on violation. | Core Team - 2025-03 |

### System Utilities

| Object Name                         | Schema | Why SECURITY DEFINER            | Risks Mitigated            | Approved By         |
| ----------------------------------- | ------ | ------------------------------- | -------------------------- | ------------------- |
| `ops_triage_alerts`                 | public | Returns ops triage alerts.      | Read-only.                 | Core Team - 2025-06 |
| `ops_triage_alerts_ack`             | public | Acknowledges triage alert.      | Alert ownership verified.  | Core Team - 2025-06 |
| `ops_triage_alerts_fetch`           | public | Fetches new triage alerts.      | Pagination limits.         | Core Team - 2025-06 |
| `dequeue_job`                       | public | Dequeues job for processing.    | Job type validation.       | Core Team - 2025-01 |
| `pgmq_delete`                       | public | Deletes PGMQ message.           | Message ID validation.     | Core Team - 2025-06 |
| `pgmq_get_queue_metrics`            | public | Returns PGMQ metrics.           | Read-only.                 | Core Team - 2025-06 |
| `pgmq_metrics`                      | public | Alternative PGMQ metrics.       | Read-only.                 | Core Team - 2025-06 |
| `trg_core_judgments_enqueue_enrich` | public | Trigger: enqueues enrichment.   | Trigger-only context.      | Core Team - 2025-03 |
| `trg_log_judgment_status_change`    | public | Trigger: logs status change.    | Trigger-only context.      | Core Team - 2025-03 |
| `pgrst_reload`                      | public | Reloads PostgREST schema cache. | Service-role only.         | Core Team - 2025-01 |
| `broadcast_live_event`              | public | Broadcasts realtime event.      | Event validation.          | Core Team - 2025-06 |
| `submit_website_lead`               | public | Submits lead from website.      | Rate limiting, validation. | Core Team - 2025-09 |

---

## ENFORCEMENT Schema Functions

| Object Name      | Schema      | Why SECURITY DEFINER                                                                     | Risks Mitigated                    | Approved By         |
| ---------------- | ----------- | ---------------------------------------------------------------------------------------- | ---------------------------------- | ------------------- |
| `record_outcome` | enforcement | Records enforcement strategy outcomes. Needs to write across multiple tables atomically. | Input validated, typed parameters. | Core Team - 2025-12 |

---

## Adding New Exceptions

To add a new SECURITY DEFINER function:

1. **Justify the need**: Document why SECURITY DEFINER is required
2. **Review the code**: Ensure no SQL injection, proper validation
3. **Add to whitelist**: Update `ALLOWED_SEC_DEFINERS` in `tests/test_security_audit_zero_trust.py`
4. **Document here**: Add a row to the appropriate table above
5. **Get approval**: Security review by Core Team member

## Audit History

| Date       | Auditor   | Action                                         |
| ---------- | --------- | ---------------------------------------------- |
| 2025-01-15 | Core Team | Initial audit, baseline whitelist              |
| 2025-03-10 | Core Team | Added enforcement functions                    |
| 2025-06-20 | Core Team | Added plaintiff, enrichment, metrics functions |
| 2025-09-15 | Core Team | Added FOIL intake, copilot functions           |
| 2025-12-22 | Core Team | Full audit, Zero Trust hardening migration     |
