-- ============================================================================
-- Migration: 20251202_cases_view_grants.sql
-- Purpose: Ensure Cases page views have proper grants for anon/authenticated
-- 
-- The /cases page uses v_judgment_pipeline. This migration ensures grants
-- are properly set on all required views and tables for the Mom Console.
-- ============================================================================
-- Grant SELECT on v_judgment_pipeline (used by /cases page)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = 'v_judgment_pipeline'
) THEN
GRANT SELECT ON public.v_judgment_pipeline TO anon,
    authenticated;
RAISE NOTICE 'Granted SELECT on public.v_judgment_pipeline to anon, authenticated';
ELSE RAISE NOTICE 'View public.v_judgment_pipeline does not exist, skipping';
END IF;
END $$;
-- Grant SELECT on v_cases (legacy/fallback view)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = 'v_cases'
) THEN
GRANT SELECT ON public.v_cases TO anon,
    authenticated;
RAISE NOTICE 'Granted SELECT on public.v_cases to anon, authenticated';
ELSE RAISE NOTICE 'View public.v_cases does not exist, skipping';
END IF;
END $$;
-- Grant SELECT on public.foil_responses (view wrapper)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = 'foil_responses'
) THEN
GRANT SELECT ON public.foil_responses TO anon,
    authenticated;
RAISE NOTICE 'Granted SELECT on public.foil_responses to anon, authenticated';
ELSE RAISE NOTICE 'View public.foil_responses does not exist, skipping';
END IF;
END $$;
-- Grant SELECT on v_collectability_snapshot (used by collectability page)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = 'v_collectability_snapshot'
) THEN
GRANT SELECT ON public.v_collectability_snapshot TO anon,
    authenticated;
RAISE NOTICE 'Granted SELECT on public.v_collectability_snapshot to anon, authenticated';
ELSE RAISE NOTICE 'View public.v_collectability_snapshot does not exist, skipping';
END IF;
END $$;
-- Grant SELECT on v_priority_pipeline (used by executive dashboard)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = 'v_priority_pipeline'
) THEN
GRANT SELECT ON public.v_priority_pipeline TO anon,
    authenticated;
RAISE NOTICE 'Granted SELECT on public.v_priority_pipeline to anon, authenticated';
ELSE RAISE NOTICE 'View public.v_priority_pipeline does not exist, skipping';
END IF;
END $$;
-- Grant SELECT on v_pipeline_snapshot (used by overview/pipeline dashboard)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = 'v_pipeline_snapshot'
) THEN
GRANT SELECT ON public.v_pipeline_snapshot TO anon,
    authenticated;
RAISE NOTICE 'Granted SELECT on public.v_pipeline_snapshot to anon, authenticated';
ELSE RAISE NOTICE 'View public.v_pipeline_snapshot does not exist, skipping';
END IF;
END $$;
-- Notify PostgREST to reload schema cache
NOTIFY pgrst,
'reload schema';
