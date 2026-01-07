-- =============================================================================
-- Zero Regret Access Layer
-- =============================================================================
-- Purpose: Replace direct view/table access with strict SECURITY DEFINER RPCs
--
-- Architecture:
--   - REVOKE all direct SELECT on views/tables from anon/authenticated
--   - Create api.* RPCs with SECURITY DEFINER that return strictly typed JSONB
--   - UI must call supabase.rpc() instead of supabase.from().select()
--
-- Security Invariants:
--   1. No table/view SELECT for anon/authenticated (except realtime/storage)
--   2. All data access goes through SECURITY DEFINER RPCs
--   3. RPC return types are strictly shaped JSONB (no raw rows)
--
-- Depends on: All prior schema migrations
-- =============================================================================
BEGIN;
-- =============================================================================
-- HELPER: Safe REVOKE function that handles missing objects
-- =============================================================================
CREATE OR REPLACE FUNCTION pg_temp.safe_revoke(
        p_privileges TEXT,
        p_object TEXT,
        p_from_roles TEXT
    ) RETURNS VOID LANGUAGE plpgsql AS $$ BEGIN EXECUTE format(
        'REVOKE %s ON %s FROM %s',
        p_privileges,
        p_object,
        p_from_roles
    );
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'Object % does not exist, skipping revoke',
p_object;
WHEN undefined_object THEN RAISE NOTICE 'Object % does not exist, skipping revoke',
p_object;
END;
$$;
-- =============================================================================
-- PART 1: CREATE api SCHEMA FOR STRICT RPCs
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS api;
COMMENT ON SCHEMA api IS 'Zero Regret API layer - strict SECURITY DEFINER RPCs only';
GRANT USAGE ON SCHEMA api TO anon,
    authenticated,
    service_role;
-- =============================================================================
-- PART 2: REVOKE DIRECT TABLE/VIEW ACCESS FROM CLIENT ROLES
-- =============================================================================
-- Note: We preserve realtime.* and storage.* as they are Supabase infrastructure
-- Note: We preserve public schema functions (pgvector, pg_trgm, etc.)
-- Analytics schema
SELECT pg_temp.safe_revoke(
        'SELECT',
        'analytics.ceo_metric_definitions',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'analytics.v_ceo_12_metrics',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'analytics.v_ceo_command_center',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'analytics.v_collectability_scores',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'analytics.v_enforcement_activity',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'analytics.v_intake_radar',
        'anon, authenticated'
    );
-- Enforcement schema
SELECT pg_temp.safe_revoke(
        'SELECT',
        'enforcement.v_candidate_wage_garnishments',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'enforcement.v_enforcement_pipeline_status',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'enforcement.v_offer_metrics',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'enforcement.v_offer_stats',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'enforcement.v_plaintiff_call_queue',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'enforcement.v_radar',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'enforcement.v_serve_jobs_active',
        'anon, authenticated'
    );
-- Enrichment schema
SELECT pg_temp.safe_revoke(
        'SELECT',
        'enrichment.contacts',
        'anon, authenticated'
    );
-- Finance schema
SELECT pg_temp.safe_revoke(
        'ALL',
        'finance.pool_nav_history',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'ALL',
        'finance.pool_transactions',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke('ALL', 'finance.pools', 'anon, authenticated');
SELECT pg_temp.safe_revoke(
        'SELECT',
        'finance.v_pool_performance',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'finance.v_portfolio_stats',
        'anon, authenticated'
    );
-- Ingestion schema  
SELECT pg_temp.safe_revoke(
        'SELECT',
        'ingestion.runs',
        'anon, authenticated'
    );
-- Intake schema
SELECT pg_temp.safe_revoke(
        'SELECT',
        'intake.v_simplicity_batch_status',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'intake.view_batch_progress',
        'anon, authenticated'
    );
-- Intelligence schema
SELECT pg_temp.safe_revoke(
        'ALL',
        'intelligence.gig_detections',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'ALL',
        'intelligence.gig_platforms',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'intelligence.v_gig_platforms_active',
        'anon, authenticated'
    );
-- Judgments schema
SELECT pg_temp.safe_revoke('ALL', 'judgments.cases', 'anon, authenticated');
SELECT pg_temp.safe_revoke(
        'ALL',
        'judgments.enrichment_runs',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'judgments.judgments',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'ALL',
        'judgments.parties',
        'anon, authenticated'
    );
-- Ops schema
SELECT pg_temp.safe_revoke(
        'SELECT',
        'ops.ingest_event_log',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'ops.v_ingest_timeline',
        'anon, authenticated'
    );
-- Public views (keeping RPC functions, revoking direct view access)
SELECT pg_temp.safe_revoke(
        'SELECT',
        'public.v_case_copilot_latest',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'public.v_enforcement_overview',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'public.v_enforcement_recent',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'public.v_enforcement_timeline',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'public.v_judgment_pipeline',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'ALL',
        'public.v_live_feed_events',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'public.v_ops_daily_summary',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'public.v_plaintiff_call_queue',
        'anon, authenticated'
    );
SELECT pg_temp.safe_revoke(
        'SELECT',
        'public.v_plaintiffs_overview',
        'anon, authenticated'
    );
-- =============================================================================
-- PART 3: CREATE STRICT SECURITY DEFINER RPCs
-- =============================================================================
-- -----------------------------------------------------------------------------
-- Dashboard Stats RPC
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.get_dashboard_stats() RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    ops,
    analytics AS $$
DECLARE result JSONB;
BEGIN
SELECT jsonb_build_object(
        'queue_depth',
        COALESCE(
            (
                SELECT COUNT(*)
                FROM ops.job_queue
                WHERE status = 'pending'
            ),
            0
        ),
        'processing_count',
        COALESCE(
            (
                SELECT COUNT(*)
                FROM ops.job_queue
                WHERE status = 'processing'
            ),
            0
        ),
        'completed_24h',
        COALESCE(
            (
                SELECT COUNT(*)
                FROM ops.job_queue
                WHERE status = 'completed'
                    AND completed_at > NOW() - INTERVAL '24 hours'
            ),
            0
        ),
        'failed_24h',
        COALESCE(
            (
                SELECT COUNT(*)
                FROM ops.job_queue
                WHERE status = 'failed'
                    AND completed_at > NOW() - INTERVAL '24 hours'
            ),
            0
        ),
        'p95_processing_seconds',
        COALESCE(
            (
                SELECT EXTRACT(
                        EPOCH
                        FROM PERCENTILE_CONT(0.95) WITHIN GROUP (
                                ORDER BY completed_at - started_at
                            )
                    )
                FROM ops.job_queue
                WHERE status = 'completed'
                    AND completed_at > NOW() - INTERVAL '24 hours'
                    AND started_at IS NOT NULL
            ),
            0
        ),
        'timestamp',
        NOW()
    ) INTO result;
RETURN result;
END;
$$;
COMMENT ON FUNCTION api.get_dashboard_stats IS 'Returns queue dashboard statistics as strictly typed JSONB';
GRANT EXECUTE ON FUNCTION api.get_dashboard_stats TO anon,
    authenticated;
-- -----------------------------------------------------------------------------
-- Plaintiffs Overview RPC
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.get_plaintiffs_overview(
        p_limit INT DEFAULT 100,
        p_offset INT DEFAULT 0,
        p_status TEXT DEFAULT NULL
    ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public AS $$
DECLARE result JSONB;
BEGIN
SELECT jsonb_build_object(
        'plaintiffs',
        COALESCE(
            (
                SELECT jsonb_agg(
                        jsonb_build_object(
                            'id',
                            p.id,
                            'name',
                            p.name,
                            'status',
                            p.status,
                            'tier',
                            p.tier,
                            'total_judgment_amount',
                            p.total_judgment_amount,
                            'created_at',
                            p.created_at
                        )
                        ORDER BY p.created_at DESC
                    )
                FROM public.plaintiffs p
                WHERE (
                        p_status IS NULL
                        OR p.status = p_status
                    )
                LIMIT p_limit OFFSET p_offset
            ),
            '[]'::jsonb
        ),
        'total_count',
        COALESCE(
            (
                SELECT COUNT(*)
                FROM public.plaintiffs p
                WHERE (
                        p_status IS NULL
                        OR p.status = p_status
                    )
            ),
            0
        ),
        'timestamp',
        NOW()
    ) INTO result;
RETURN result;
END;
$$;
COMMENT ON FUNCTION api.get_plaintiffs_overview IS 'Returns paginated plaintiff overview as strictly typed JSONB';
GRANT EXECUTE ON FUNCTION api.get_plaintiffs_overview TO anon,
    authenticated;
-- -----------------------------------------------------------------------------
-- Judgment Pipeline RPC
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.get_judgment_pipeline(
        p_limit INT DEFAULT 50,
        p_offset INT DEFAULT 0
    ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    judgments AS $$
DECLARE result JSONB;
BEGIN
SELECT jsonb_build_object(
        'judgments',
        COALESCE(
            (
                SELECT jsonb_agg(
                        jsonb_build_object(
                            'id',
                            j.id,
                            'case_number',
                            j.case_number,
                            'judgment_amount',
                            j.judgment_amount,
                            'status',
                            j.status,
                            'priority',
                            j.priority,
                            'enforcement_stage',
                            j.enforcement_stage,
                            'created_at',
                            j.created_at
                        )
                        ORDER BY CASE
                                j.priority
                                WHEN 'high' THEN 1
                                WHEN 'medium' THEN 2
                                ELSE 3
                            END,
                            j.created_at DESC
                    )
                FROM public.judgments j
                LIMIT p_limit OFFSET p_offset
            ),
            '[]'::jsonb
        ),
        'total_count',
        COALESCE(
            (
                SELECT COUNT(*)
                FROM public.judgments
            ),
            0
        ),
        'timestamp',
        NOW()
    ) INTO result;
RETURN result;
END;
$$;
COMMENT ON FUNCTION api.get_judgment_pipeline IS 'Returns judgment pipeline as strictly typed JSONB';
GRANT EXECUTE ON FUNCTION api.get_judgment_pipeline TO anon,
    authenticated;
-- -----------------------------------------------------------------------------
-- Enforcement Overview RPC
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.get_enforcement_overview() RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    enforcement AS $$
DECLARE result JSONB;
BEGIN
SELECT jsonb_build_object(
        'total_judgments',
        COALESCE(
            (
                SELECT COUNT(*)
                FROM public.judgments
            ),
            0
        ),
        'active_enforcement',
        COALESCE(
            (
                SELECT COUNT(*)
                FROM public.judgments
                WHERE enforcement_stage IS NOT NULL
                    AND enforcement_stage != 'closed'
            ),
            0
        ),
        'total_amount',
        COALESCE(
            (
                SELECT SUM(judgment_amount)
                FROM public.judgments
            ),
            0
        ),
        'collected_amount',
        COALESCE(
            (
                SELECT SUM(collected_amount)
                FROM public.judgments
            ),
            0
        ),
        'by_stage',
        COALESCE(
            (
                SELECT jsonb_object_agg(
                        COALESCE(enforcement_stage, 'unassigned'),
                        stage_count
                    )
                FROM (
                        SELECT enforcement_stage,
                            COUNT(*) as stage_count
                        FROM public.judgments
                        GROUP BY enforcement_stage
                    ) s
            ),
            '{}'::jsonb
        ),
        'timestamp',
        NOW()
    ) INTO result;
RETURN result;
END;
$$;
COMMENT ON FUNCTION api.get_enforcement_overview IS 'Returns enforcement overview metrics as strictly typed JSONB';
GRANT EXECUTE ON FUNCTION api.get_enforcement_overview TO anon,
    authenticated;
-- -----------------------------------------------------------------------------
-- Call Queue RPC
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.get_call_queue(p_limit INT DEFAULT 50) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public AS $$
DECLARE result JSONB;
BEGIN
SELECT jsonb_build_object(
        'queue',
        COALESCE(
            (
                SELECT jsonb_agg(
                        jsonb_build_object(
                            'plaintiff_id',
                            p.id,
                            'plaintiff_name',
                            p.name,
                            'tier',
                            p.tier,
                            'status',
                            p.status,
                            'last_contact_at',
                            p.last_contact_at,
                            'next_action_at',
                            p.next_action_at,
                            'total_judgment_amount',
                            p.total_judgment_amount
                        )
                        ORDER BY CASE
                                p.tier
                                WHEN 'whale' THEN 1
                                WHEN 'high' THEN 2
                                WHEN 'medium' THEN 3
                                ELSE 4
                            END,
                            p.next_action_at ASC NULLS LAST
                    )
                FROM public.plaintiffs p
                WHERE p.status IN ('active', 'pending_contact', 'negotiating')
                    AND (
                        p.next_action_at IS NULL
                        OR p.next_action_at <= NOW() + INTERVAL '7 days'
                    )
                LIMIT p_limit
            ), '[]'::jsonb
        ), 'timestamp', NOW()
    ) INTO result;
RETURN result;
END;
$$;
COMMENT ON FUNCTION api.get_call_queue IS 'Returns prioritized call queue as strictly typed JSONB';
GRANT EXECUTE ON FUNCTION api.get_call_queue TO anon,
    authenticated;
-- -----------------------------------------------------------------------------
-- CEO Metrics RPC
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.get_ceo_metrics() RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    analytics AS $$
DECLARE result JSONB;
BEGIN -- Call existing CEO metrics function and wrap in strict structure
SELECT jsonb_build_object(
        'metrics',
        COALESCE(public.ceo_12_metrics(), '[]'::jsonb),
        'timestamp',
        NOW()
    ) INTO result;
RETURN result;
END;
$$;
COMMENT ON FUNCTION api.get_ceo_metrics IS 'Returns CEO 12 metrics as strictly typed JSONB';
GRANT EXECUTE ON FUNCTION api.get_ceo_metrics TO anon,
    authenticated;
-- -----------------------------------------------------------------------------
-- Intake Stats RPC
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.get_intake_stats() RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    intake AS $$
DECLARE result JSONB;
BEGIN
SELECT jsonb_build_object(
        'pending_batches',
        COALESCE(
            (
                SELECT COUNT(*)
                FROM intake.simplicity_batches
                WHERE status = 'pending'
            ),
            0
        ),
        'processing_batches',
        COALESCE(
            (
                SELECT COUNT(*)
                FROM intake.simplicity_batches
                WHERE status = 'processing'
            ),
            0
        ),
        'completed_24h',
        COALESCE(
            (
                SELECT COUNT(*)
                FROM intake.simplicity_batches
                WHERE status = 'completed'
                    AND updated_at > NOW() - INTERVAL '24 hours'
            ),
            0
        ),
        'failed_24h',
        COALESCE(
            (
                SELECT COUNT(*)
                FROM intake.simplicity_batches
                WHERE status = 'failed'
                    AND updated_at > NOW() - INTERVAL '24 hours'
            ),
            0
        ),
        'total_rows_processed_24h',
        COALESCE(
            (
                SELECT SUM(total_rows)
                FROM intake.simplicity_batches
                WHERE status = 'completed'
                    AND updated_at > NOW() - INTERVAL '24 hours'
            ),
            0
        ),
        'timestamp',
        NOW()
    ) INTO result;
RETURN result;
END;
$$;
COMMENT ON FUNCTION api.get_intake_stats IS 'Returns intake batch statistics as strictly typed JSONB';
GRANT EXECUTE ON FUNCTION api.get_intake_stats TO anon,
    authenticated;
-- -----------------------------------------------------------------------------
-- Ingest Timeline RPC (for ops visibility)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.get_ingest_timeline(
        p_limit INT DEFAULT 100,
        p_batch_id UUID DEFAULT NULL
    ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$
DECLARE result JSONB;
BEGIN
SELECT jsonb_build_object(
        'events',
        COALESCE(
            (
                SELECT jsonb_agg(
                        jsonb_build_object(
                            'id',
                            e.id,
                            'event_type',
                            e.event_type,
                            'stage',
                            e.stage,
                            'created_at',
                            e.created_at,
                            'payload',
                            e.payload - 'sensitive_data' -- Strip any sensitive fields
                        )
                        ORDER BY e.created_at DESC
                    )
                FROM ops.ingest_event_log e
                WHERE (
                        p_batch_id IS NULL
                        OR e.batch_id = p_batch_id
                    )
                LIMIT p_limit
            ), '[]'::jsonb
        ), 'timestamp', NOW()
    ) INTO result;
RETURN result;
END;
$$;
COMMENT ON FUNCTION api.get_ingest_timeline IS 'Returns ingest event timeline as strictly typed JSONB';
GRANT EXECUTE ON FUNCTION api.get_ingest_timeline TO anon,
    authenticated;
-- =============================================================================
-- PART 4: LOCK DOWN ops.queue_job RPCs (already exist but verify grants)
-- =============================================================================
-- Ensure queue_job RPCs are only accessible to authenticated (not anon)
-- Use DO block with exception handler for missing functions
DO $$ BEGIN EXECUTE 'REVOKE EXECUTE ON FUNCTION ops.queue_job FROM anon';
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'ops.queue_job function not found, skipping revoke';
END $$;
DO $$ BEGIN EXECUTE 'REVOKE EXECUTE ON FUNCTION ops.queue_job_idempotent FROM anon';
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'ops.queue_job_idempotent function not found, skipping revoke';
END $$;
COMMIT;
