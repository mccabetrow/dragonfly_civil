-- =============================================================================
-- 0302_rls_role_policies.sql
-- Dragonfly Civil – Role-Based Policies for All Tables
-- =============================================================================
-- POLICY MATRIX:
--   admin         : SELECT, INSERT, UPDATE, DELETE on all tables
--   ops           : SELECT all, UPDATE (status, notes, follow_up_date) - no DELETE
--   ceo           : SELECT all financial/case data - no modifications
--   enrichment_bot: SELECT, UPDATE enrichment columns only
--   outreach_bot  : SELECT, UPDATE call outcome columns only
--   service_role  : Full access (for n8n, workers, backend)
-- =============================================================================
BEGIN;
-- =============================================================================
-- HELPER: Operational columns that ops can update
-- =============================================================================
-- These are the only columns ops users may modify:
--   status, ops_notes, follow_up_date, notes, note, assigned_to, assignee
-- =============================================================================
-- PUBLIC.JUDGMENTS POLICIES
-- =============================================================================
DROP POLICY IF EXISTS judgments_service_all ON public.judgments;
DROP POLICY IF EXISTS judgments_admin_all ON public.judgments;
DROP POLICY IF EXISTS judgments_read_authorized ON public.judgments;
DROP POLICY IF EXISTS judgments_ops_update ON public.judgments;
DROP POLICY IF EXISTS judgments_select_public ON public.judgments;
DROP POLICY IF EXISTS judgments_insert_service ON public.judgments;
DROP POLICY IF EXISTS judgments_update_service ON public.judgments;
DROP POLICY IF EXISTS judgments_delete_service ON public.judgments;
-- Service role: full access (for n8n, workers)
CREATE POLICY judgments_service_all ON public.judgments FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
-- Admin: full access
CREATE POLICY judgments_admin_all ON public.judgments FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
-- CEO, Ops, Bots: read access
CREATE POLICY judgments_read_authorized ON public.judgments FOR
SELECT USING (public.dragonfly_can_read());
-- Ops: update operational fields only (enforcement_stage, notes, priority_level)
-- Note: Column-level restrictions enforced via RPC, policy allows row access
CREATE POLICY judgments_ops_update ON public.judgments FOR
UPDATE USING (public.dragonfly_has_role('ops')) WITH CHECK (public.dragonfly_has_role('ops'));
-- Enrichment bot: update enrichment-related fields
CREATE POLICY judgments_enrichment_update ON public.judgments FOR
UPDATE USING (public.dragonfly_has_role('enrichment_bot')) WITH CHECK (public.dragonfly_has_role('enrichment_bot'));
GRANT SELECT ON public.judgments TO authenticated;
GRANT UPDATE ON public.judgments TO authenticated;
-- =============================================================================
-- PUBLIC.PLAINTIFFS POLICIES
-- =============================================================================
DROP POLICY IF EXISTS plaintiffs_service_all ON public.plaintiffs;
DROP POLICY IF EXISTS plaintiffs_admin_all ON public.plaintiffs;
DROP POLICY IF EXISTS plaintiffs_read_authorized ON public.plaintiffs;
DROP POLICY IF EXISTS plaintiffs_ops_update ON public.plaintiffs;
CREATE POLICY plaintiffs_service_all ON public.plaintiffs FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY plaintiffs_admin_all ON public.plaintiffs FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY plaintiffs_read_authorized ON public.plaintiffs FOR
SELECT USING (public.dragonfly_can_read());
CREATE POLICY plaintiffs_ops_update ON public.plaintiffs FOR
UPDATE USING (public.dragonfly_has_role('ops')) WITH CHECK (public.dragonfly_has_role('ops'));
GRANT SELECT ON public.plaintiffs TO authenticated;
GRANT UPDATE ON public.plaintiffs TO authenticated;
-- =============================================================================
-- PUBLIC.PLAINTIFF_CONTACTS POLICIES
-- =============================================================================
DROP POLICY IF EXISTS plaintiff_contacts_service_all ON public.plaintiff_contacts;
DROP POLICY IF EXISTS plaintiff_contacts_admin_all ON public.plaintiff_contacts;
DROP POLICY IF EXISTS plaintiff_contacts_read_authorized ON public.plaintiff_contacts;
DROP POLICY IF EXISTS plaintiff_contacts_ops_update ON public.plaintiff_contacts;
CREATE POLICY plaintiff_contacts_service_all ON public.plaintiff_contacts FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY plaintiff_contacts_admin_all ON public.plaintiff_contacts FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY plaintiff_contacts_read_authorized ON public.plaintiff_contacts FOR
SELECT USING (public.dragonfly_can_read());
CREATE POLICY plaintiff_contacts_ops_update ON public.plaintiff_contacts FOR
UPDATE USING (public.dragonfly_has_role('ops')) WITH CHECK (public.dragonfly_has_role('ops'));
GRANT SELECT ON public.plaintiff_contacts TO authenticated;
GRANT UPDATE ON public.plaintiff_contacts TO authenticated;
-- =============================================================================
-- PUBLIC.PLAINTIFF_STATUS_HISTORY POLICIES
-- =============================================================================
DROP POLICY IF EXISTS plaintiff_status_history_service_all ON public.plaintiff_status_history;
DROP POLICY IF EXISTS plaintiff_status_history_admin_all ON public.plaintiff_status_history;
DROP POLICY IF EXISTS plaintiff_status_history_read_authorized ON public.plaintiff_status_history;
DROP POLICY IF EXISTS plaintiff_status_history_ops_insert ON public.plaintiff_status_history;
CREATE POLICY plaintiff_status_history_service_all ON public.plaintiff_status_history FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY plaintiff_status_history_admin_all ON public.plaintiff_status_history FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY plaintiff_status_history_read_authorized ON public.plaintiff_status_history FOR
SELECT USING (public.dragonfly_can_read());
-- Ops can INSERT status history (append-only audit)
CREATE POLICY plaintiff_status_history_ops_insert ON public.plaintiff_status_history FOR
INSERT WITH CHECK (public.dragonfly_has_role('ops'));
GRANT SELECT,
    INSERT ON public.plaintiff_status_history TO authenticated;
-- =============================================================================
-- PUBLIC.PLAINTIFF_TASKS POLICIES
-- =============================================================================
DROP POLICY IF EXISTS plaintiff_tasks_service_all ON public.plaintiff_tasks;
DROP POLICY IF EXISTS plaintiff_tasks_admin_all ON public.plaintiff_tasks;
DROP POLICY IF EXISTS plaintiff_tasks_read_authorized ON public.plaintiff_tasks;
DROP POLICY IF EXISTS plaintiff_tasks_ops_modify ON public.plaintiff_tasks;
CREATE POLICY plaintiff_tasks_service_all ON public.plaintiff_tasks FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY plaintiff_tasks_admin_all ON public.plaintiff_tasks FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY plaintiff_tasks_read_authorized ON public.plaintiff_tasks FOR
SELECT USING (public.dragonfly_can_read());
-- Ops can create and update tasks
CREATE POLICY plaintiff_tasks_ops_modify ON public.plaintiff_tasks FOR ALL USING (public.dragonfly_has_role('ops')) WITH CHECK (public.dragonfly_has_role('ops'));
GRANT SELECT,
    INSERT,
    UPDATE ON public.plaintiff_tasks TO authenticated;
-- =============================================================================
-- PUBLIC.PLAINTIFF_CALL_ATTEMPTS POLICIES
-- =============================================================================
DROP POLICY IF EXISTS plaintiff_call_attempts_service_all ON public.plaintiff_call_attempts;
DROP POLICY IF EXISTS plaintiff_call_attempts_admin_all ON public.plaintiff_call_attempts;
DROP POLICY IF EXISTS plaintiff_call_attempts_read_authorized ON public.plaintiff_call_attempts;
DROP POLICY IF EXISTS plaintiff_call_attempts_outreach_insert ON public.plaintiff_call_attempts;
DROP POLICY IF EXISTS plaintiff_call_attempts_ops_insert ON public.plaintiff_call_attempts;
CREATE POLICY plaintiff_call_attempts_service_all ON public.plaintiff_call_attempts FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY plaintiff_call_attempts_admin_all ON public.plaintiff_call_attempts FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY plaintiff_call_attempts_read_authorized ON public.plaintiff_call_attempts FOR
SELECT USING (public.dragonfly_can_read());
-- Outreach bot can INSERT call attempts
CREATE POLICY plaintiff_call_attempts_outreach_insert ON public.plaintiff_call_attempts FOR
INSERT WITH CHECK (public.dragonfly_has_role('outreach_bot'));
-- Outreach bot can UPDATE call outcomes
CREATE POLICY plaintiff_call_attempts_outreach_update ON public.plaintiff_call_attempts FOR
UPDATE USING (public.dragonfly_has_role('outreach_bot')) WITH CHECK (public.dragonfly_has_role('outreach_bot'));
-- Ops can also log call attempts
CREATE POLICY plaintiff_call_attempts_ops_insert ON public.plaintiff_call_attempts FOR
INSERT WITH CHECK (public.dragonfly_has_role('ops'));
GRANT SELECT,
    INSERT,
    UPDATE ON public.plaintiff_call_attempts TO authenticated;
-- =============================================================================
-- PUBLIC.ENFORCEMENT_CASES POLICIES
-- =============================================================================
DROP POLICY IF EXISTS enforcement_cases_service_all ON public.enforcement_cases;
DROP POLICY IF EXISTS enforcement_cases_admin_all ON public.enforcement_cases;
DROP POLICY IF EXISTS enforcement_cases_read_authorized ON public.enforcement_cases;
DROP POLICY IF EXISTS enforcement_cases_ops_update ON public.enforcement_cases;
DROP POLICY IF EXISTS enforcement_cases_read ON public.enforcement_cases;
DROP POLICY IF EXISTS enforcement_cases_write ON public.enforcement_cases;
DROP POLICY IF EXISTS enforcement_cases_rw ON public.enforcement_cases;
CREATE POLICY enforcement_cases_service_all ON public.enforcement_cases FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY enforcement_cases_admin_all ON public.enforcement_cases FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY enforcement_cases_read_authorized ON public.enforcement_cases FOR
SELECT USING (public.dragonfly_can_read());
CREATE POLICY enforcement_cases_ops_update ON public.enforcement_cases FOR
UPDATE USING (public.dragonfly_has_role('ops')) WITH CHECK (public.dragonfly_has_role('ops'));
GRANT SELECT,
    UPDATE ON public.enforcement_cases TO authenticated;
-- =============================================================================
-- PUBLIC.ENFORCEMENT_EVENTS POLICIES
-- =============================================================================
DROP POLICY IF EXISTS enforcement_events_service_all ON public.enforcement_events;
DROP POLICY IF EXISTS enforcement_events_admin_all ON public.enforcement_events;
DROP POLICY IF EXISTS enforcement_events_read_authorized ON public.enforcement_events;
DROP POLICY IF EXISTS enforcement_events_ops_insert ON public.enforcement_events;
DROP POLICY IF EXISTS enforcement_events_read ON public.enforcement_events;
DROP POLICY IF EXISTS enforcement_events_write ON public.enforcement_events;
CREATE POLICY enforcement_events_service_all ON public.enforcement_events FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY enforcement_events_admin_all ON public.enforcement_events FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY enforcement_events_read_authorized ON public.enforcement_events FOR
SELECT USING (public.dragonfly_can_read());
-- Ops can INSERT events (audit trail)
CREATE POLICY enforcement_events_ops_insert ON public.enforcement_events FOR
INSERT WITH CHECK (public.dragonfly_has_role('ops'));
GRANT SELECT,
    INSERT ON public.enforcement_events TO authenticated;
-- =============================================================================
-- PUBLIC.ENFORCEMENT_TIMELINE POLICIES
-- =============================================================================
DO $$ BEGIN IF to_regclass('public.enforcement_timeline') IS NOT NULL THEN DROP POLICY IF EXISTS enforcement_timeline_service_all ON public.enforcement_timeline;
DROP POLICY IF EXISTS enforcement_timeline_admin_all ON public.enforcement_timeline;
DROP POLICY IF EXISTS enforcement_timeline_read_authorized ON public.enforcement_timeline;
CREATE POLICY enforcement_timeline_service_all ON public.enforcement_timeline FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY enforcement_timeline_admin_all ON public.enforcement_timeline FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY enforcement_timeline_read_authorized ON public.enforcement_timeline FOR
SELECT USING (public.dragonfly_can_read());
GRANT SELECT ON public.enforcement_timeline TO authenticated;
END IF;
END $$;
-- =============================================================================
-- PUBLIC.ENFORCEMENT_EVIDENCE POLICIES
-- =============================================================================
DO $$ BEGIN IF to_regclass('public.enforcement_evidence') IS NOT NULL THEN DROP POLICY IF EXISTS enforcement_evidence_service_all ON public.enforcement_evidence;
DROP POLICY IF EXISTS enforcement_evidence_admin_all ON public.enforcement_evidence;
DROP POLICY IF EXISTS enforcement_evidence_read_authorized ON public.enforcement_evidence;
CREATE POLICY enforcement_evidence_service_all ON public.enforcement_evidence FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY enforcement_evidence_admin_all ON public.enforcement_evidence FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY enforcement_evidence_read_authorized ON public.enforcement_evidence FOR
SELECT USING (public.dragonfly_can_read());
GRANT SELECT ON public.enforcement_evidence TO authenticated;
END IF;
END $$;
-- =============================================================================
-- PUBLIC.ENFORCEMENT_ACTIONS POLICIES
-- =============================================================================
DO $$ BEGIN IF to_regclass('public.enforcement_actions') IS NOT NULL THEN DROP POLICY IF EXISTS enforcement_actions_service_all ON public.enforcement_actions;
DROP POLICY IF EXISTS enforcement_actions_admin_all ON public.enforcement_actions;
DROP POLICY IF EXISTS enforcement_actions_read_authorized ON public.enforcement_actions;
DROP POLICY IF EXISTS enforcement_actions_ops_update ON public.enforcement_actions;
CREATE POLICY enforcement_actions_service_all ON public.enforcement_actions FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY enforcement_actions_admin_all ON public.enforcement_actions FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY enforcement_actions_read_authorized ON public.enforcement_actions FOR
SELECT USING (public.dragonfly_can_read());
CREATE POLICY enforcement_actions_ops_update ON public.enforcement_actions FOR
UPDATE USING (public.dragonfly_has_role('ops')) WITH CHECK (public.dragonfly_has_role('ops'));
GRANT SELECT,
    UPDATE ON public.enforcement_actions TO authenticated;
END IF;
END $$;
-- =============================================================================
-- PUBLIC.EVIDENCE_FILES POLICIES
-- =============================================================================
DROP POLICY IF EXISTS evidence_files_service_all ON public.evidence_files;
DROP POLICY IF EXISTS evidence_files_admin_all ON public.evidence_files;
DROP POLICY IF EXISTS evidence_files_read_authorized ON public.evidence_files;
DROP POLICY IF EXISTS evidence_files_read ON public.evidence_files;
DROP POLICY IF EXISTS evidence_files_write ON public.evidence_files;
CREATE POLICY evidence_files_service_all ON public.evidence_files FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY evidence_files_admin_all ON public.evidence_files FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY evidence_files_read_authorized ON public.evidence_files FOR
SELECT USING (public.dragonfly_can_read());
GRANT SELECT ON public.evidence_files TO authenticated;
-- =============================================================================
-- PUBLIC.OUTREACH_LOG POLICIES (conditional - table may not exist)
-- =============================================================================
DO $$ BEGIN IF to_regclass('public.outreach_log') IS NOT NULL THEN DROP POLICY IF EXISTS outreach_log_service_all ON public.outreach_log;
DROP POLICY IF EXISTS outreach_log_admin_all ON public.outreach_log;
DROP POLICY IF EXISTS outreach_log_read_authorized ON public.outreach_log;
DROP POLICY IF EXISTS outreach_log_outreach_insert ON public.outreach_log;
DROP POLICY IF EXISTS outreach_log_outreach_update ON public.outreach_log;
CREATE POLICY outreach_log_service_all ON public.outreach_log FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY outreach_log_admin_all ON public.outreach_log FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY outreach_log_read_authorized ON public.outreach_log FOR
SELECT USING (public.dragonfly_can_read());
CREATE POLICY outreach_log_outreach_insert ON public.outreach_log FOR
INSERT WITH CHECK (public.dragonfly_has_role('outreach_bot'));
CREATE POLICY outreach_log_outreach_update ON public.outreach_log FOR
UPDATE USING (public.dragonfly_has_role('outreach_bot')) WITH CHECK (public.dragonfly_has_role('outreach_bot'));
CREATE POLICY outreach_log_ops_modify ON public.outreach_log FOR ALL USING (public.dragonfly_has_role('ops')) WITH CHECK (public.dragonfly_has_role('ops'));
GRANT SELECT,
    INSERT,
    UPDATE ON public.outreach_log TO authenticated;
ELSE RAISE NOTICE 'Table public.outreach_log does not exist, skipping RLS policies';
END IF;
END $$;
-- =============================================================================
-- PUBLIC.COMMUNICATIONS POLICIES (FDCPA protected)
-- =============================================================================
DO $$ BEGIN IF to_regclass('public.communications') IS NOT NULL THEN DROP POLICY IF EXISTS communications_service_all ON public.communications;
DROP POLICY IF EXISTS communications_admin_all ON public.communications;
DROP POLICY IF EXISTS communications_read_authorized ON public.communications;
DROP POLICY IF EXISTS communications_outreach_insert ON public.communications;
CREATE POLICY communications_service_all ON public.communications FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY communications_admin_all ON public.communications FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY communications_read_authorized ON public.communications FOR
SELECT USING (public.dragonfly_can_read());
-- Outreach bot can log communications
CREATE POLICY communications_outreach_insert ON public.communications FOR
INSERT WITH CHECK (public.dragonfly_has_role('outreach_bot'));
GRANT SELECT,
    INSERT ON public.communications TO authenticated;
END IF;
END $$;
-- =============================================================================
-- PUBLIC.IMPORT_RUNS POLICIES
-- =============================================================================
DROP POLICY IF EXISTS import_runs_service_all ON public.import_runs;
DROP POLICY IF EXISTS import_runs_admin_all ON public.import_runs;
DROP POLICY IF EXISTS import_runs_read_authorized ON public.import_runs;
DROP POLICY IF EXISTS import_runs_service_rw ON public.import_runs;
CREATE POLICY import_runs_service_all ON public.import_runs FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY import_runs_admin_all ON public.import_runs FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY import_runs_read_authorized ON public.import_runs FOR
SELECT USING (public.dragonfly_can_read());
GRANT SELECT ON public.import_runs TO authenticated;
-- =============================================================================
-- PUBLIC.CASE_COPILOT_LOGS POLICIES
-- =============================================================================
DROP POLICY IF EXISTS case_copilot_logs_service_all ON public.case_copilot_logs;
DROP POLICY IF EXISTS case_copilot_logs_admin_all ON public.case_copilot_logs;
DROP POLICY IF EXISTS case_copilot_logs_read_authorized ON public.case_copilot_logs;
CREATE POLICY case_copilot_logs_service_all ON public.case_copilot_logs FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY case_copilot_logs_admin_all ON public.case_copilot_logs FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY case_copilot_logs_read_authorized ON public.case_copilot_logs FOR
SELECT USING (public.dragonfly_can_read());
GRANT SELECT ON public.case_copilot_logs TO authenticated;
-- =============================================================================
-- PUBLIC.ENFORCEMENT_HISTORY POLICIES
-- =============================================================================
DO $$ BEGIN IF to_regclass('public.enforcement_history') IS NOT NULL THEN DROP POLICY IF EXISTS enforcement_history_service_all ON public.enforcement_history;
DROP POLICY IF EXISTS enforcement_history_admin_all ON public.enforcement_history;
DROP POLICY IF EXISTS enforcement_history_read_authorized ON public.enforcement_history;
DROP POLICY IF EXISTS enforcement_history_ops_insert ON public.enforcement_history;
CREATE POLICY enforcement_history_service_all ON public.enforcement_history FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY enforcement_history_admin_all ON public.enforcement_history FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY enforcement_history_read_authorized ON public.enforcement_history FOR
SELECT USING (public.dragonfly_can_read());
-- Ops can append to history (audit trail)
CREATE POLICY enforcement_history_ops_insert ON public.enforcement_history FOR
INSERT WITH CHECK (public.dragonfly_has_role('ops'));
GRANT SELECT,
    INSERT ON public.enforcement_history TO authenticated;
END IF;
END $$;
-- =============================================================================
-- PUBLIC.JUDGMENT_PRIORITY_HISTORY POLICIES
-- =============================================================================
DO $$ BEGIN IF to_regclass('public.judgment_priority_history') IS NOT NULL THEN DROP POLICY IF EXISTS judgment_priority_history_service_all ON public.judgment_priority_history;
DROP POLICY IF EXISTS judgment_priority_history_admin_all ON public.judgment_priority_history;
DROP POLICY IF EXISTS judgment_priority_history_read_authorized ON public.judgment_priority_history;
CREATE POLICY judgment_priority_history_service_all ON public.judgment_priority_history FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY judgment_priority_history_admin_all ON public.judgment_priority_history FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY judgment_priority_history_read_authorized ON public.judgment_priority_history FOR
SELECT USING (public.dragonfly_can_read());
GRANT SELECT ON public.judgment_priority_history TO authenticated;
END IF;
END $$;
-- =============================================================================
-- CORE_JUDGMENTS / DEBTOR_INTELLIGENCE POLICIES
-- =============================================================================
DO $$ BEGIN IF to_regclass('public.core_judgments') IS NOT NULL THEN DROP POLICY IF EXISTS core_judgments_service_all ON public.core_judgments;
DROP POLICY IF EXISTS core_judgments_admin_all ON public.core_judgments;
DROP POLICY IF EXISTS core_judgments_read_authorized ON public.core_judgments;
DROP POLICY IF EXISTS core_judgments_enrichment_update ON public.core_judgments;
CREATE POLICY core_judgments_service_all ON public.core_judgments FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY core_judgments_admin_all ON public.core_judgments FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY core_judgments_read_authorized ON public.core_judgments FOR
SELECT USING (public.dragonfly_can_read());
-- Enrichment bot can update enrichment fields
CREATE POLICY core_judgments_enrichment_update ON public.core_judgments FOR
UPDATE USING (public.dragonfly_has_role('enrichment_bot')) WITH CHECK (public.dragonfly_has_role('enrichment_bot'));
GRANT SELECT,
    UPDATE ON public.core_judgments TO authenticated;
END IF;
END $$;
DO $$ BEGIN IF to_regclass('public.debtor_intelligence') IS NOT NULL THEN DROP POLICY IF EXISTS debtor_intelligence_service_all ON public.debtor_intelligence;
DROP POLICY IF EXISTS debtor_intelligence_admin_all ON public.debtor_intelligence;
DROP POLICY IF EXISTS debtor_intelligence_read_authorized ON public.debtor_intelligence;
DROP POLICY IF EXISTS debtor_intelligence_enrichment_modify ON public.debtor_intelligence;
CREATE POLICY debtor_intelligence_service_all ON public.debtor_intelligence FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY debtor_intelligence_admin_all ON public.debtor_intelligence FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY debtor_intelligence_read_authorized ON public.debtor_intelligence FOR
SELECT USING (public.dragonfly_can_read());
-- Enrichment bot can INSERT and UPDATE debtor intelligence
CREATE POLICY debtor_intelligence_enrichment_modify ON public.debtor_intelligence FOR ALL USING (public.dragonfly_has_role('enrichment_bot')) WITH CHECK (public.dragonfly_has_role('enrichment_bot'));
GRANT SELECT,
    INSERT,
    UPDATE ON public.debtor_intelligence TO authenticated;
END IF;
END $$;
-- =============================================================================
-- EXTERNAL_DATA_CALLS (FCRA audit - append only)
-- =============================================================================
DO $$ BEGIN IF to_regclass('public.external_data_calls') IS NOT NULL THEN DROP POLICY IF EXISTS external_data_calls_service_all ON public.external_data_calls;
DROP POLICY IF EXISTS external_data_calls_admin_read ON public.external_data_calls;
DROP POLICY IF EXISTS external_data_calls_enrichment_insert ON public.external_data_calls;
CREATE POLICY external_data_calls_service_all ON public.external_data_calls FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
-- Only admins can read FCRA audit logs
CREATE POLICY external_data_calls_admin_read ON public.external_data_calls FOR
SELECT USING (public.dragonfly_has_role('admin'));
-- Enrichment bot can INSERT audit entries
CREATE POLICY external_data_calls_enrichment_insert ON public.external_data_calls FOR
INSERT WITH CHECK (public.dragonfly_has_role('enrichment_bot'));
GRANT SELECT ON public.external_data_calls TO authenticated;
GRANT INSERT ON public.external_data_calls TO authenticated;
END IF;
END $$;
-- =============================================================================
-- OPS_METADATA / OPS_TRIAGE_ALERTS POLICIES
-- =============================================================================
DO $$ BEGIN IF to_regclass('public.ops_metadata') IS NOT NULL THEN DROP POLICY IF EXISTS ops_metadata_service_all ON public.ops_metadata;
DROP POLICY IF EXISTS ops_metadata_admin_all ON public.ops_metadata;
DROP POLICY IF EXISTS ops_metadata_ops_all ON public.ops_metadata;
CREATE POLICY ops_metadata_service_all ON public.ops_metadata FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY ops_metadata_admin_all ON public.ops_metadata FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY ops_metadata_ops_all ON public.ops_metadata FOR ALL USING (public.dragonfly_has_role('ops')) WITH CHECK (public.dragonfly_has_role('ops'));
GRANT ALL ON public.ops_metadata TO authenticated;
END IF;
END $$;
DO $$ BEGIN IF to_regclass('public.ops_triage_alerts') IS NOT NULL THEN DROP POLICY IF EXISTS ops_triage_alerts_service_all ON public.ops_triage_alerts;
DROP POLICY IF EXISTS ops_triage_alerts_admin_all ON public.ops_triage_alerts;
DROP POLICY IF EXISTS ops_triage_alerts_ops_all ON public.ops_triage_alerts;
CREATE POLICY ops_triage_alerts_service_all ON public.ops_triage_alerts FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY ops_triage_alerts_admin_all ON public.ops_triage_alerts FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY ops_triage_alerts_ops_all ON public.ops_triage_alerts FOR ALL USING (public.dragonfly_has_role('ops')) WITH CHECK (public.dragonfly_has_role('ops'));
GRANT ALL ON public.ops_triage_alerts TO authenticated;
END IF;
END $$;
-- =============================================================================
-- JUDGMENTS SCHEMA POLICIES
-- =============================================================================
-- judgments.cases
DO $$ BEGIN IF to_regclass('judgments.cases') IS NOT NULL THEN DROP POLICY IF EXISTS jcases_service_all ON judgments.cases;
DROP POLICY IF EXISTS jcases_admin_all ON judgments.cases;
DROP POLICY IF EXISTS jcases_read_authorized ON judgments.cases;
DROP POLICY IF EXISTS jcases_enrichment_update ON judgments.cases;
CREATE POLICY jcases_service_all ON judgments.cases FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY jcases_admin_all ON judgments.cases FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY jcases_read_authorized ON judgments.cases FOR
SELECT USING (public.dragonfly_can_read());
CREATE POLICY jcases_enrichment_update ON judgments.cases FOR
UPDATE USING (public.dragonfly_has_role('enrichment_bot')) WITH CHECK (public.dragonfly_has_role('enrichment_bot'));
GRANT SELECT,
    UPDATE ON judgments.cases TO authenticated;
END IF;
END $$;
-- judgments.judgments
DO $$ BEGIN IF to_regclass('judgments.judgments') IS NOT NULL THEN DROP POLICY IF EXISTS jjudgments_service_all ON judgments.judgments;
DROP POLICY IF EXISTS jjudgments_admin_all ON judgments.judgments;
DROP POLICY IF EXISTS jjudgments_read_authorized ON judgments.judgments;
CREATE POLICY jjudgments_service_all ON judgments.judgments FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY jjudgments_admin_all ON judgments.judgments FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY jjudgments_read_authorized ON judgments.judgments FOR
SELECT USING (public.dragonfly_can_read());
GRANT SELECT ON judgments.judgments TO authenticated;
END IF;
END $$;
-- judgments.parties
DO $$ BEGIN IF to_regclass('judgments.parties') IS NOT NULL THEN DROP POLICY IF EXISTS jparties_service_all ON judgments.parties;
DROP POLICY IF EXISTS jparties_admin_all ON judgments.parties;
DROP POLICY IF EXISTS jparties_read_authorized ON judgments.parties;
DROP POLICY IF EXISTS jparties_enrichment_update ON judgments.parties;
CREATE POLICY jparties_service_all ON judgments.parties FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY jparties_admin_all ON judgments.parties FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY jparties_read_authorized ON judgments.parties FOR
SELECT USING (public.dragonfly_can_read());
CREATE POLICY jparties_enrichment_update ON judgments.parties FOR
UPDATE USING (public.dragonfly_has_role('enrichment_bot')) WITH CHECK (public.dragonfly_has_role('enrichment_bot'));
GRANT SELECT,
    UPDATE ON judgments.parties TO authenticated;
END IF;
END $$;
-- judgments.contacts
DO $$ BEGIN IF to_regclass('judgments.contacts') IS NOT NULL THEN DROP POLICY IF EXISTS jcontacts_service_all ON judgments.contacts;
DROP POLICY IF EXISTS jcontacts_admin_all ON judgments.contacts;
DROP POLICY IF EXISTS jcontacts_read_authorized ON judgments.contacts;
DROP POLICY IF EXISTS jcontacts_enrichment_modify ON judgments.contacts;
CREATE POLICY jcontacts_service_all ON judgments.contacts FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY jcontacts_admin_all ON judgments.contacts FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY jcontacts_read_authorized ON judgments.contacts FOR
SELECT USING (public.dragonfly_can_read());
CREATE POLICY jcontacts_enrichment_modify ON judgments.contacts FOR ALL USING (public.dragonfly_has_role('enrichment_bot')) WITH CHECK (public.dragonfly_has_role('enrichment_bot'));
GRANT SELECT,
    INSERT,
    UPDATE ON judgments.contacts TO authenticated;
END IF;
END $$;
-- judgments.enrichment_runs
DO $$ BEGIN IF to_regclass('judgments.enrichment_runs') IS NOT NULL THEN DROP POLICY IF EXISTS jenrichment_runs_service_all ON judgments.enrichment_runs;
DROP POLICY IF EXISTS jenrichment_runs_admin_all ON judgments.enrichment_runs;
DROP POLICY IF EXISTS jenrichment_runs_read_authorized ON judgments.enrichment_runs;
DROP POLICY IF EXISTS jenrichment_runs_enrichment_modify ON judgments.enrichment_runs;
DROP POLICY IF EXISTS enrichment_runs_service_select ON judgments.enrichment_runs;
DROP POLICY IF EXISTS enrichment_runs_service_insert ON judgments.enrichment_runs;
DROP POLICY IF EXISTS enrichment_runs_service_update ON judgments.enrichment_runs;
DROP POLICY IF EXISTS enrichment_runs_service_delete ON judgments.enrichment_runs;
CREATE POLICY jenrichment_runs_service_all ON judgments.enrichment_runs FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY jenrichment_runs_admin_all ON judgments.enrichment_runs FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY jenrichment_runs_read_authorized ON judgments.enrichment_runs FOR
SELECT USING (public.dragonfly_can_read());
CREATE POLICY jenrichment_runs_enrichment_modify ON judgments.enrichment_runs FOR ALL USING (public.dragonfly_has_role('enrichment_bot')) WITH CHECK (public.dragonfly_has_role('enrichment_bot'));
GRANT SELECT,
    INSERT,
    UPDATE ON judgments.enrichment_runs TO authenticated;
END IF;
END $$;
-- judgments.foil_responses
DO $$ BEGIN IF to_regclass('judgments.foil_responses') IS NOT NULL THEN DROP POLICY IF EXISTS jfoil_service_all ON judgments.foil_responses;
DROP POLICY IF EXISTS jfoil_admin_all ON judgments.foil_responses;
DROP POLICY IF EXISTS jfoil_read_authorized ON judgments.foil_responses;
DROP POLICY IF EXISTS foil_responses_service_select ON judgments.foil_responses;
DROP POLICY IF EXISTS foil_responses_service_insert ON judgments.foil_responses;
DROP POLICY IF EXISTS foil_responses_service_update ON judgments.foil_responses;
DROP POLICY IF EXISTS foil_responses_service_delete ON judgments.foil_responses;
CREATE POLICY jfoil_service_all ON judgments.foil_responses FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY jfoil_admin_all ON judgments.foil_responses FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY jfoil_read_authorized ON judgments.foil_responses FOR
SELECT USING (public.dragonfly_can_read());
GRANT SELECT ON judgments.foil_responses TO authenticated;
END IF;
END $$;
-- ingestion.runs
DO $$ BEGIN IF to_regclass('ingestion.runs') IS NOT NULL THEN DROP POLICY IF EXISTS ingestion_runs_service_all ON ingestion.runs;
DROP POLICY IF EXISTS ingestion_runs_admin_all ON ingestion.runs;
DROP POLICY IF EXISTS ingestion_runs_read_authorized ON ingestion.runs;
CREATE POLICY ingestion_runs_service_all ON ingestion.runs FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY ingestion_runs_admin_all ON ingestion.runs FOR ALL USING (public.dragonfly_has_role('admin')) WITH CHECK (public.dragonfly_has_role('admin'));
CREATE POLICY ingestion_runs_read_authorized ON ingestion.runs FOR
SELECT USING (public.dragonfly_can_read());
GRANT SELECT ON ingestion.runs TO authenticated;
END IF;
END $$;
-- =============================================================================
-- FINAL: Reload PostgREST schema cache
-- =============================================================================
SELECT public.pgrst_reload();
COMMIT;