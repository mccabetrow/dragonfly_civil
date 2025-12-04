-- =============================================================================
-- 0301_rls_enable_force.sql
-- Dragonfly Civil – Enable & Force RLS on ALL tables
-- =============================================================================
-- This migration enables RLS on every table in the public and judgments schemas.
-- FORCE ROW LEVEL SECURITY ensures even table owners must pass policy checks.
-- =============================================================================
BEGIN;
-- =============================================================================
-- PUBLIC SCHEMA TABLES
-- =============================================================================
-- Core tables that need RLS enforcement
DO $$
DECLARE target text;
public_tables text [] := ARRAY [
        -- Core judgment/enforcement tables
        'judgments',
        'judgment_priority_history',
        'enforcement_history',
        'enforcement_cases',
        'enforcement_events',
        'enforcement_timeline',
        'enforcement_evidence',
        'enforcement_actions',
        'evidence_files',
        
        -- Plaintiff/intake tables
        'plaintiffs',
        'plaintiff_contacts',
        'plaintiff_status_history',
        'plaintiff_tasks',
        'plaintiff_call_attempts',
        
        -- Outreach/communications
        'outreach_log',
        'communications',
        
        -- Core judgment schema tables
        'core_judgments',
        'debtor_intelligence',
        
        -- Audit/compliance tables
        'external_data_calls',
        'import_runs',
        'case_copilot_logs',
        
        -- Ops tables
        'ops_metadata',
        'ops_triage_alerts'
    ];
BEGIN FOREACH target IN ARRAY public_tables LOOP -- Check if table exists before enabling RLS
IF to_regclass(format('public.%I', target)) IS NOT NULL THEN EXECUTE format(
    'ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;',
    target
);
EXECUTE format(
    'ALTER TABLE public.%I FORCE ROW LEVEL SECURITY;',
    target
);
RAISE NOTICE 'RLS enabled and forced on public.%',
target;
ELSE RAISE NOTICE 'Table public.% does not exist, skipping',
target;
END IF;
END LOOP;
END $$;
-- =============================================================================
-- JUDGMENTS SCHEMA TABLES
-- =============================================================================
DO $$
DECLARE target text;
judgments_tables text [] := ARRAY [
        'cases',
        'judgments',
        'parties',
        'contacts',
        'foil_responses',
        'enrichment_runs'
    ];
BEGIN FOREACH target IN ARRAY judgments_tables LOOP IF to_regclass(format('judgments.%I', target)) IS NOT NULL THEN EXECUTE format(
    'ALTER TABLE judgments.%I ENABLE ROW LEVEL SECURITY;',
    target
);
EXECUTE format(
    'ALTER TABLE judgments.%I FORCE ROW LEVEL SECURITY;',
    target
);
RAISE NOTICE 'RLS enabled and forced on judgments.%',
target;
ELSE RAISE NOTICE 'Table judgments.% does not exist, skipping',
target;
END IF;
END LOOP;
END $$;
-- =============================================================================
-- INGESTION SCHEMA TABLES
-- =============================================================================
DO $$ BEGIN IF to_regclass('ingestion.runs') IS NOT NULL THEN
ALTER TABLE ingestion.runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion.runs FORCE ROW LEVEL SECURITY;
RAISE NOTICE 'RLS enabled and forced on ingestion.runs';
END IF;
END $$;
-- =============================================================================
-- REVOKE PUBLIC/ANON ACCESS ON SENSITIVE TABLES
-- =============================================================================
-- Following least-privilege principle: revoke everything, then grant specifically
DO $$
DECLARE target text;
public_tables text [] := ARRAY [
        'judgments',
        'judgment_priority_history',
        'enforcement_history',
        'enforcement_cases',
        'enforcement_events',
        'enforcement_timeline',
        'enforcement_evidence',
        'enforcement_actions',
        'evidence_files',
        'plaintiffs',
        'plaintiff_contacts',
        'plaintiff_status_history',
        'plaintiff_tasks',
        'plaintiff_call_attempts',
        'outreach_log',
        'communications',
        'core_judgments',
        'debtor_intelligence',
        'external_data_calls',
        'import_runs',
        'case_copilot_logs',
        'ops_metadata',
        'ops_triage_alerts',
        'dragonfly_role_mappings',
        'dragonfly_role_audit_log'
    ];
BEGIN FOREACH target IN ARRAY public_tables LOOP IF to_regclass(format('public.%I', target)) IS NOT NULL THEN EXECUTE format('REVOKE ALL ON public.%I FROM public;', target);
EXECUTE format('REVOKE ALL ON public.%I FROM anon;', target);
-- Grant service_role full access (needed for n8n/workers)
EXECUTE format(
    'GRANT ALL ON public.%I TO service_role;',
    target
);
END IF;
END LOOP;
END $$;
DO $$
DECLARE target text;
judgments_tables text [] := ARRAY ['cases', 'judgments', 'parties', 'contacts', 'foil_responses', 'enrichment_runs'];
BEGIN FOREACH target IN ARRAY judgments_tables LOOP IF to_regclass(format('judgments.%I', target)) IS NOT NULL THEN EXECUTE format(
    'REVOKE ALL ON judgments.%I FROM public;',
    target
);
EXECUTE format('REVOKE ALL ON judgments.%I FROM anon;', target);
EXECUTE format(
    'GRANT ALL ON judgments.%I TO service_role;',
    target
);
END IF;
END LOOP;
END $$;
-- ingestion schema
DO $$ BEGIN IF to_regclass('ingestion.runs') IS NOT NULL THEN REVOKE ALL ON ingestion.runs
FROM public;
REVOKE ALL ON ingestion.runs
FROM anon;
GRANT ALL ON ingestion.runs TO service_role;
END IF;
END $$;
COMMENT ON SCHEMA public IS 'Dragonfly Civil public schema – RLS enforced on all tables.';
SELECT public.pgrst_reload();
COMMIT;