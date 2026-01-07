-- Migration: 20260801_security_hardening.sql
-- Purpose: Audit-proof SECURITY DEFINER functions and enable security_invoker on views
-- Author: Principal Database Security Architect
-- Date: 2026-01-07
--
-- This migration addresses Supabase Advisor security warnings by:
-- 1. Setting explicit search_path on all SECURITY DEFINER functions
-- 2. Converting standard views to security_invoker mode
--
-- Context:
-- - SECURITY DEFINER functions execute with the owner's privileges
-- - Without fixed search_path, attackers can hijack function behavior
-- - Views with security_invoker = true respect RLS on underlying tables
--
-- Reference: https://supabase.com/docs/guides/database/database-advisors
BEGIN;
-- =============================================================================
-- PART 1: FUNCTION HARDENING (Search Path Fix)
-- =============================================================================
-- All SECURITY DEFINER functions must have explicit, minimal search_path
-- to prevent search_path hijacking attacks.
--
-- Pattern: SET search_path = <required_schemas>, pg_temp
-- pg_temp is included to prevent temp table hijacking
DO $banner$ BEGIN RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
RAISE NOTICE '  SECURITY HARDENING: Function search_path sanitization';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
END $banner$;
-- -----------------------------------------------------------------------------
-- 1.1 Critical API Functions
-- -----------------------------------------------------------------------------
-- These are the main RPCs exposed to authenticated users
DO $$ BEGIN -- api.transition_case_stage - Core state engine
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'api'
        AND p.proname = 'transition_case_stage'
) THEN ALTER FUNCTION api.transition_case_stage
SET search_path = api,
    public,
    pg_temp;
RAISE NOTICE '✓ api.transition_case_stage: search_path = api, public, pg_temp';
END IF;
-- api.get_dashboard_stats
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'api'
        AND p.proname = 'get_dashboard_stats'
) THEN ALTER FUNCTION api.get_dashboard_stats
SET search_path = api,
    public,
    pg_temp;
RAISE NOTICE '✓ api.get_dashboard_stats: search_path = api, public, pg_temp';
END IF;
-- api.get_plaintiff_details
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'api'
        AND p.proname = 'get_plaintiff_details'
) THEN ALTER FUNCTION api.get_plaintiff_details
SET search_path = api,
    public,
    pg_temp;
RAISE NOTICE '✓ api.get_plaintiff_details: search_path = api, public, pg_temp';
END IF;
-- api.get_judgment_details
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'api'
        AND p.proname = 'get_judgment_details'
) THEN ALTER FUNCTION api.get_judgment_details
SET search_path = api,
    public,
    pg_temp;
RAISE NOTICE '✓ api.get_judgment_details: search_path = api, public, pg_temp';
END IF;
-- api.get_enforcement_overview
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'api'
        AND p.proname = 'get_enforcement_overview'
) THEN ALTER FUNCTION api.get_enforcement_overview
SET search_path = api,
    public,
    enforcement,
    pg_temp;
RAISE NOTICE '✓ api.get_enforcement_overview: search_path = api, public, enforcement, pg_temp';
END IF;
-- api.get_call_queue
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'api'
        AND p.proname = 'get_call_queue'
) THEN ALTER FUNCTION api.get_call_queue
SET search_path = api,
    public,
    pg_temp;
RAISE NOTICE '✓ api.get_call_queue: search_path = api, public, pg_temp';
END IF;
-- api.get_ceo_metrics
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'api'
        AND p.proname = 'get_ceo_metrics'
) THEN ALTER FUNCTION api.get_ceo_metrics
SET search_path = api,
    public,
    pg_temp;
RAISE NOTICE '✓ api.get_ceo_metrics: search_path = api, public, pg_temp';
END IF;
-- api.get_intake_stats
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'api'
        AND p.proname = 'get_intake_stats'
) THEN ALTER FUNCTION api.get_intake_stats
SET search_path = api,
    public,
    intake,
    pg_temp;
RAISE NOTICE '✓ api.get_intake_stats: search_path = api, public, intake, pg_temp';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- 1.2 Audit Functions (Court-Proof Critical)
-- -----------------------------------------------------------------------------
-- These functions must NEVER be compromised - they create legal evidence
DO $$ BEGIN -- audit.log_event - Primary audit logging
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'audit'
        AND p.proname = 'log_event'
) THEN ALTER FUNCTION audit.log_event
SET search_path = audit,
    pg_temp;
RAISE NOTICE '✓ audit.log_event: search_path = audit, pg_temp';
END IF;
-- audit.prevent_modification - Trigger function
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'audit'
        AND p.proname = 'prevent_modification'
) THEN ALTER FUNCTION audit.prevent_modification
SET search_path = audit,
    pg_temp;
RAISE NOTICE '✓ audit.prevent_modification: search_path = audit, pg_temp';
END IF;
-- audit.prevent_tamper - Trigger function
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'audit'
        AND p.proname = 'prevent_tamper'
) THEN ALTER FUNCTION audit.prevent_tamper
SET search_path = audit,
    pg_temp;
RAISE NOTICE '✓ audit.prevent_tamper: search_path = audit, pg_temp';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- 1.3 Evidence Functions (Chain of Custody)
-- -----------------------------------------------------------------------------
DO $$ BEGIN -- evidence.register_file - Primary evidence ingestion point
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'evidence'
        AND p.proname = 'register_file'
) THEN ALTER FUNCTION evidence.register_file
SET search_path = evidence,
    audit,
    pg_temp;
RAISE NOTICE '✓ evidence.register_file: search_path = evidence, audit, pg_temp';
END IF;
-- evidence.enforce_rpc_registration - Trigger
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'evidence'
        AND p.proname = 'enforce_rpc_registration'
) THEN ALTER FUNCTION evidence.enforce_rpc_registration
SET search_path = evidence,
    pg_temp;
RAISE NOTICE '✓ evidence.enforce_rpc_registration: search_path = evidence, pg_temp';
END IF;
-- evidence.enforce_legal_hold - Trigger
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'evidence'
        AND p.proname = 'enforce_legal_hold'
) THEN ALTER FUNCTION evidence.enforce_legal_hold
SET search_path = evidence,
    pg_temp;
RAISE NOTICE '✓ evidence.enforce_legal_hold: search_path = evidence, pg_temp';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- 1.4 Legal Functions (Authorization)
-- -----------------------------------------------------------------------------
DO $$ BEGIN -- legal.is_authorized - Critical enforcement gate
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'legal'
        AND p.proname = 'is_authorized'
) THEN ALTER FUNCTION legal.is_authorized
SET search_path = legal,
    pg_temp;
RAISE NOTICE '✓ legal.is_authorized: search_path = legal, pg_temp';
END IF;
-- legal.record_consent
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'legal'
        AND p.proname = 'record_consent'
) THEN ALTER FUNCTION legal.record_consent
SET search_path = legal,
    audit,
    pg_temp;
RAISE NOTICE '✓ legal.record_consent: search_path = legal, audit, pg_temp';
END IF;
-- legal.revoke_consent
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'legal'
        AND p.proname = 'revoke_consent'
) THEN ALTER FUNCTION legal.revoke_consent
SET search_path = legal,
    audit,
    pg_temp;
RAISE NOTICE '✓ legal.revoke_consent: search_path = legal, audit, pg_temp';
END IF;
-- legal.get_consent_document_hash
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'legal'
        AND p.proname = 'get_consent_document_hash'
) THEN ALTER FUNCTION legal.get_consent_document_hash
SET search_path = legal,
    pg_temp;
RAISE NOTICE '✓ legal.get_consent_document_hash: search_path = legal, pg_temp';
END IF;
-- legal.log_consent_change - Trigger
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'legal'
        AND p.proname = 'log_consent_change'
) THEN ALTER FUNCTION legal.log_consent_change
SET search_path = legal,
    audit,
    pg_temp;
RAISE NOTICE '✓ legal.log_consent_change: search_path = legal, audit, pg_temp';
END IF;
-- legal.update_consent_timestamp - Trigger
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'legal'
        AND p.proname = 'update_consent_timestamp'
) THEN ALTER FUNCTION legal.update_consent_timestamp
SET search_path = legal,
    pg_temp;
RAISE NOTICE '✓ legal.update_consent_timestamp: search_path = legal, pg_temp';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- 1.5 Tenant Functions (Multi-tenancy)
-- -----------------------------------------------------------------------------
DO $$ BEGIN -- tenant.user_org_ids - Critical for RLS
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'tenant'
        AND p.proname = 'user_org_ids'
) THEN ALTER FUNCTION tenant.user_org_ids
SET search_path = tenant,
    pg_temp;
RAISE NOTICE '✓ tenant.user_org_ids: search_path = tenant, pg_temp';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- 1.6 Operations Functions
-- -----------------------------------------------------------------------------
DO $$ BEGIN -- ops.get_system_contract_hash
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'ops'
        AND p.proname = 'get_system_contract_hash'
) THEN ALTER FUNCTION ops.get_system_contract_hash
SET search_path = ops,
    pg_temp;
RAISE NOTICE '✓ ops.get_system_contract_hash: search_path = ops, pg_temp';
END IF;
-- ops.capture_contract_snapshot
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'ops'
        AND p.proname = 'capture_contract_snapshot'
) THEN ALTER FUNCTION ops.capture_contract_snapshot
SET search_path = ops,
    pg_temp;
RAISE NOTICE '✓ ops.capture_contract_snapshot: search_path = ops, pg_temp';
END IF;
-- ops.claim_outbox_messages
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'ops'
        AND p.proname = 'claim_outbox_messages'
) THEN ALTER FUNCTION ops.claim_outbox_messages
SET search_path = ops,
    pg_temp;
RAISE NOTICE '✓ ops.claim_outbox_messages: search_path = ops, pg_temp';
END IF;
-- ops.complete_outbox_message
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'ops'
        AND p.proname = 'complete_outbox_message'
) THEN ALTER FUNCTION ops.complete_outbox_message
SET search_path = ops,
    pg_temp;
RAISE NOTICE '✓ ops.complete_outbox_message: search_path = ops, pg_temp';
END IF;
-- ops.fail_outbox_message
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'ops'
        AND p.proname = 'fail_outbox_message'
) THEN ALTER FUNCTION ops.fail_outbox_message
SET search_path = ops,
    pg_temp;
RAISE NOTICE '✓ ops.fail_outbox_message: search_path = ops, pg_temp';
END IF;
-- ops.insert_outbox_message
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'ops'
        AND p.proname = 'insert_outbox_message'
) THEN ALTER FUNCTION ops.insert_outbox_message
SET search_path = ops,
    pg_temp;
RAISE NOTICE '✓ ops.insert_outbox_message: search_path = ops, pg_temp';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- 1.7 Worker Functions
-- -----------------------------------------------------------------------------
DO $$ BEGIN -- workers.upsert_heartbeat
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'workers'
        AND p.proname = 'upsert_heartbeat'
) THEN ALTER FUNCTION workers.upsert_heartbeat
SET search_path = workers,
    pg_temp;
RAISE NOTICE '✓ workers.upsert_heartbeat: search_path = workers, pg_temp';
END IF;
-- workers.reap_stale
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'workers'
        AND p.proname = 'reap_stale'
) THEN ALTER FUNCTION workers.reap_stale
SET search_path = workers,
    pg_temp;
RAISE NOTICE '✓ workers.reap_stale: search_path = workers, pg_temp';
END IF;
-- workers.claim_job
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'workers'
        AND p.proname = 'claim_job'
) THEN ALTER FUNCTION workers.claim_job
SET search_path = workers,
    pg_temp;
RAISE NOTICE '✓ workers.claim_job: search_path = workers, pg_temp';
END IF;
-- workers.complete_job
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'workers'
        AND p.proname = 'complete_job'
) THEN ALTER FUNCTION workers.complete_job
SET search_path = workers,
    pg_temp;
RAISE NOTICE '✓ workers.complete_job: search_path = workers, pg_temp';
END IF;
-- workers.fail_job
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'workers'
        AND p.proname = 'fail_job'
) THEN ALTER FUNCTION workers.fail_job
SET search_path = workers,
    pg_temp;
RAISE NOTICE '✓ workers.fail_job: search_path = workers, pg_temp';
END IF;
-- workers.update_metrics
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'workers'
        AND p.proname = 'update_metrics'
) THEN ALTER FUNCTION workers.update_metrics
SET search_path = workers,
    pg_temp;
RAISE NOTICE '✓ workers.update_metrics: search_path = workers, pg_temp';
END IF;
-- workers.move_to_dlq
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'workers'
        AND p.proname = 'move_to_dlq'
) THEN ALTER FUNCTION workers.move_to_dlq
SET search_path = workers,
    pg_temp;
RAISE NOTICE '✓ workers.move_to_dlq: search_path = workers, pg_temp';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- 1.8 Security Functions
-- -----------------------------------------------------------------------------
DO $$ BEGIN -- security.log_incident
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'security'
        AND p.proname = 'log_incident'
) THEN ALTER FUNCTION security.log_incident
SET search_path = security,
    pg_temp;
RAISE NOTICE '✓ security.log_incident: search_path = security, pg_temp';
END IF;
-- security.get_incidents_24h
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'security'
        AND p.proname = 'get_incidents_24h'
) THEN ALTER FUNCTION security.get_incidents_24h
SET search_path = security,
    pg_temp;
RAISE NOTICE '✓ security.get_incidents_24h: search_path = security, pg_temp';
END IF;
-- security.get_incident_stats
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'security'
        AND p.proname = 'get_incident_stats'
) THEN ALTER FUNCTION security.get_incident_stats
SET search_path = security,
    pg_temp;
RAISE NOTICE '✓ security.get_incident_stats: search_path = security, pg_temp';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- 1.9 RAG Functions
-- -----------------------------------------------------------------------------
DO $$ BEGIN -- rag.search_documents
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'rag'
        AND p.proname = 'search_documents'
) THEN ALTER FUNCTION rag.search_documents
SET search_path = rag,
    evidence,
    pg_temp;
RAISE NOTICE '✓ rag.search_documents: search_path = rag, evidence, pg_temp';
END IF;
-- rag.get_document_chunks
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'rag'
        AND p.proname = 'get_document_chunks'
) THEN ALTER FUNCTION rag.get_document_chunks
SET search_path = rag,
    pg_temp;
RAISE NOTICE '✓ rag.get_document_chunks: search_path = rag, pg_temp';
END IF;
-- rag.queue_document
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'rag'
        AND p.proname = 'queue_document'
) THEN ALTER FUNCTION rag.queue_document
SET search_path = rag,
    evidence,
    pg_temp;
RAISE NOTICE '✓ rag.queue_document: search_path = rag, evidence, pg_temp';
END IF;
-- rag.complete_processing
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'rag'
        AND p.proname = 'complete_processing'
) THEN ALTER FUNCTION rag.complete_processing
SET search_path = rag,
    pg_temp;
RAISE NOTICE '✓ rag.complete_processing: search_path = rag, pg_temp';
END IF;
-- rag.fail_processing
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'rag'
        AND p.proname = 'fail_processing'
) THEN ALTER FUNCTION rag.fail_processing
SET search_path = rag,
    pg_temp;
RAISE NOTICE '✓ rag.fail_processing: search_path = rag, pg_temp';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- 1.10 Public Schema Trigger Functions
-- -----------------------------------------------------------------------------
DO $$ BEGIN -- public.auto_create_case_state
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
        AND p.proname = 'auto_create_case_state'
) THEN ALTER FUNCTION public.auto_create_case_state
SET search_path = public,
    pg_temp;
RAISE NOTICE '✓ public.auto_create_case_state: search_path = public, pg_temp';
END IF;
-- public.upsert_plaintiff
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
        AND p.proname = 'upsert_plaintiff'
) THEN ALTER FUNCTION public.upsert_plaintiff
SET search_path = public,
    pg_temp;
RAISE NOTICE '✓ public.upsert_plaintiff: search_path = public, pg_temp';
END IF;
-- public.upsert_judgment
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
        AND p.proname = 'upsert_judgment'
) THEN ALTER FUNCTION public.upsert_judgment
SET search_path = public,
    pg_temp;
RAISE NOTICE '✓ public.upsert_judgment: search_path = public, pg_temp';
END IF;
END $$;
-- =============================================================================
-- PART 2: VIEW SECURITY (Security Invoker Switch)
-- =============================================================================
-- Views with security_invoker = true run queries with the calling user's
-- permissions, ensuring RLS policies on underlying tables are checked.
--
-- CRITICAL: Only convert views that don't NEED elevated privileges.
-- Views that aggregate across orgs for admin use should remain SECURITY DEFINER.
DO $banner$ BEGIN RAISE NOTICE '';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
RAISE NOTICE '  SECURITY HARDENING: View security_invoker conversion';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
END $banner$;
-- -----------------------------------------------------------------------------
-- 2.1 Public Schema Views (RLS-enforced)
-- -----------------------------------------------------------------------------
DO $$ BEGIN -- public.v_plaintiffs_overview - Should respect RLS
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = 'v_plaintiffs_overview'
) THEN ALTER VIEW public.v_plaintiffs_overview
SET (security_invoker = true);
RAISE NOTICE '✓ public.v_plaintiffs_overview: security_invoker = true';
END IF;
-- public.v_judgment_pipeline - Should respect RLS
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = 'v_judgment_pipeline'
) THEN ALTER VIEW public.v_judgment_pipeline
SET (security_invoker = true);
RAISE NOTICE '✓ public.v_judgment_pipeline: security_invoker = true';
END IF;
-- public.v_plaintiff_summary - Should respect RLS
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = 'v_plaintiff_summary'
) THEN ALTER VIEW public.v_plaintiff_summary
SET (security_invoker = true);
RAISE NOTICE '✓ public.v_plaintiff_summary: security_invoker = true';
END IF;
-- public.v_cases_full - Should respect RLS
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = 'v_cases_full'
) THEN ALTER VIEW public.v_cases_full
SET (security_invoker = true);
RAISE NOTICE '✓ public.v_cases_full: security_invoker = true';
END IF;
-- public.v_plaintiff_open_tasks - Should respect RLS
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = 'v_plaintiff_open_tasks'
) THEN ALTER VIEW public.v_plaintiff_open_tasks
SET (security_invoker = true);
RAISE NOTICE '✓ public.v_plaintiff_open_tasks: security_invoker = true';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- 2.2 Enforcement Schema Views (RLS-enforced)
-- -----------------------------------------------------------------------------
DO $$ BEGIN -- enforcement.v_authorized_plaintiffs - Should respect RLS
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'enforcement'
        AND table_name = 'v_authorized_plaintiffs'
) THEN ALTER VIEW enforcement.v_authorized_plaintiffs
SET (security_invoker = true);
RAISE NOTICE '✓ enforcement.v_authorized_plaintiffs: security_invoker = true';
END IF;
-- enforcement.v_unauthorized_plaintiffs - Should respect RLS  
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'enforcement'
        AND table_name = 'v_unauthorized_plaintiffs'
) THEN ALTER VIEW enforcement.v_unauthorized_plaintiffs
SET (security_invoker = true);
RAISE NOTICE '✓ enforcement.v_unauthorized_plaintiffs: security_invoker = true';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- 2.3 Workers Schema Views (Internal - security_invoker)
-- -----------------------------------------------------------------------------
DO $$ BEGIN -- workers.v_worker_health
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'workers'
        AND table_name = 'v_worker_health'
) THEN ALTER VIEW workers.v_worker_health
SET (security_invoker = true);
RAISE NOTICE '✓ workers.v_worker_health: security_invoker = true';
END IF;
-- workers.v_queue_metrics
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'workers'
        AND table_name = 'v_queue_metrics'
) THEN ALTER VIEW workers.v_queue_metrics
SET (security_invoker = true);
RAISE NOTICE '✓ workers.v_queue_metrics: security_invoker = true';
END IF;
-- workers.v_queue_stats
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'workers'
        AND table_name = 'v_queue_stats'
) THEN ALTER VIEW workers.v_queue_stats
SET (security_invoker = true);
RAISE NOTICE '✓ workers.v_queue_stats: security_invoker = true';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- 2.4 Intake Schema Views (Internal - security_invoker)
-- -----------------------------------------------------------------------------
DO $$ BEGIN -- intake.v_batch_summary
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'intake'
        AND table_name = 'v_batch_summary'
) THEN ALTER VIEW intake.v_batch_summary
SET (security_invoker = true);
RAISE NOTICE '✓ intake.v_batch_summary: security_invoker = true';
END IF;
-- intake.view_batch_progress
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'intake'
        AND table_name = 'view_batch_progress'
) THEN ALTER VIEW intake.view_batch_progress
SET (security_invoker = true);
RAISE NOTICE '✓ intake.view_batch_progress: security_invoker = true';
END IF;
-- intake.view_batch_metrics
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'intake'
        AND table_name = 'view_batch_metrics'
) THEN ALTER VIEW intake.view_batch_metrics
SET (security_invoker = true);
RAISE NOTICE '✓ intake.view_batch_metrics: security_invoker = true';
END IF;
-- intake.v_batch_observability
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'intake'
        AND table_name = 'v_batch_observability'
) THEN ALTER VIEW intake.v_batch_observability
SET (security_invoker = true);
RAISE NOTICE '✓ intake.v_batch_observability: security_invoker = true';
END IF;
-- intake.v_error_summary
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'intake'
        AND table_name = 'v_error_summary'
) THEN ALTER VIEW intake.v_error_summary
SET (security_invoker = true);
RAISE NOTICE '✓ intake.v_error_summary: security_invoker = true';
END IF;
END $$;
-- =============================================================================
-- PART 3: VERIFICATION
-- =============================================================================
DO $banner$ BEGIN RAISE NOTICE '';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
RAISE NOTICE '  VERIFICATION: Checking hardened functions';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
END $banner$;
DO $$
DECLARE v_count_hardened INT;
v_count_unhardened INT;
v_unhardened_list TEXT;
BEGIN -- Count SECURITY DEFINER functions WITH explicit search_path
SELECT COUNT(*) INTO v_count_hardened
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE p.prosecdef = true
    AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'extensions')
    AND p.proconfig IS NOT NULL
    AND EXISTS (
        SELECT 1
        FROM unnest(p.proconfig) AS conf
        WHERE conf LIKE 'search_path=%'
    );
-- Count SECURITY DEFINER functions WITHOUT explicit search_path
SELECT COUNT(*) INTO v_count_unhardened
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE p.prosecdef = true
    AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'extensions')
    AND (
        p.proconfig IS NULL
        OR NOT EXISTS (
            SELECT 1
            FROM unnest(p.proconfig) AS conf
            WHERE conf LIKE 'search_path=%'
        )
    );
-- List unhardened functions (first 10)
SELECT string_agg(
        n.nspname || '.' || p.proname,
        ', '
        ORDER BY n.nspname,
            p.proname
    ) INTO v_unhardened_list
FROM (
        SELECT n.nspname,
            p.proname
        FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE p.prosecdef = true
            AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'extensions')
            AND (
                p.proconfig IS NULL
                OR NOT EXISTS (
                    SELECT 1
                    FROM unnest(p.proconfig) AS conf
                    WHERE conf LIKE 'search_path=%'
                )
            )
        LIMIT 10
    ) sub
    JOIN pg_proc p ON TRUE
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname || '.' || p.proname = sub.nspname || '.' || sub.proname;
RAISE NOTICE '✓ SECURITY DEFINER functions with explicit search_path: %',
v_count_hardened;
IF v_count_unhardened > 0 THEN RAISE NOTICE '⚠ SECURITY DEFINER functions WITHOUT search_path: % (first 10: %)',
v_count_unhardened,
COALESCE(v_unhardened_list, 'none listed');
ELSE RAISE NOTICE '✓ All SECURITY DEFINER functions have explicit search_path';
END IF;
END $$;
-- Count views with security_invoker
DO $$
DECLARE v_invoker_count INT;
BEGIN
SELECT COUNT(*) INTO v_invoker_count
FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
WHERE c.relkind = 'v'
    AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    AND c.reloptions IS NOT NULL
    AND 'security_invoker=true' = ANY(c.reloptions);
RAISE NOTICE '✓ Views with security_invoker = true: %',
v_invoker_count;
END $$;
DO $banner$ BEGIN RAISE NOTICE '';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
RAISE NOTICE '  SECURITY HARDENING COMPLETE';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
END $banner$;
COMMIT;
-- =============================================================================
-- DOCUMENTATION
-- =============================================================================
COMMENT ON SCHEMA public IS 'Public schema - hardened 2026-01-07 (search_path + security_invoker)';