-- ============================================================================
-- Migration: Compliance Foundation
-- Purpose: Data classification, multi-tenancy, and RLS enforcement
-- Date: 2026-01-01
-- ============================================================================
-- ============================================================================
-- PART 1: Tenant Schema & Organization Infrastructure
-- ============================================================================
-- Create tenant schema for multi-tenancy (cannot use auth.* - it's protected)
CREATE SCHEMA IF NOT EXISTS tenant;
COMMENT ON SCHEMA tenant IS 'Multi-tenancy infrastructure for organization isolation';
-- Create organizations table
CREATE TABLE IF NOT EXISTS tenant.orgs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE tenant.orgs IS '{"description": "Organization tenants for multi-tenancy isolation", "sensitivity": "INTERNAL"}';
-- Create organization memberships (links users to orgs)
CREATE TABLE IF NOT EXISTS tenant.org_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    -- References auth.users but no FK due to schema protection
    org_id UUID NOT NULL REFERENCES tenant.orgs(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, org_id)
);
COMMENT ON TABLE tenant.org_memberships IS '{"description": "User-to-organization membership mapping", "sensitivity": "INTERNAL"}';
-- Index for fast membership lookups
CREATE INDEX IF NOT EXISTS idx_org_memberships_user_id ON tenant.org_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_org_memberships_org_id ON tenant.org_memberships(org_id);
-- ============================================================================
-- PART 2: Helper Function - Get user's org_ids
-- ============================================================================
CREATE OR REPLACE FUNCTION tenant.user_org_ids() RETURNS SETOF UUID LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = tenant,
    public AS $$
SELECT org_id
FROM tenant.org_memberships
WHERE user_id = auth.uid();
$$;
COMMENT ON FUNCTION tenant.user_org_ids() IS 'Returns all org_ids the current user belongs to';
-- Grant execute to authenticated users
GRANT USAGE ON SCHEMA tenant TO authenticated,
    service_role;
GRANT SELECT ON tenant.org_memberships TO authenticated;
GRANT SELECT ON tenant.orgs TO authenticated;
GRANT EXECUTE ON FUNCTION tenant.user_org_ids() TO authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA tenant TO service_role;
-- ============================================================================
-- PART 3: Data Classification Comments (Existing Tables Only)
-- ============================================================================
-- Classification Schema:
-- {
--   "tag": "PUBLIC" | "INTERNAL" | "CONFIDENTIAL" | "PII" | "FINANCIAL",
--   "sensitivity": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
--   "description": "Human-readable description"
-- }
-- Note: Column comments are applied conditionally only if tables exist
-- This allows the migration to run even if legacy tables don't exist
DO $$ BEGIN -- Check if judgments table exists and add comments
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
) THEN -- Table comment
EXECUTE $sql$COMMENT ON TABLE public.judgments IS '{"description": "Core judgment records from court filings", "sensitivity": "HIGH", "contains_pii": true}' $sql$;
-- Add org_id if it doesn't exist
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'org_id'
) THEN EXECUTE 'ALTER TABLE public.judgments ADD COLUMN org_id UUID REFERENCES tenant.orgs(id)';
EXECUTE 'CREATE INDEX IF NOT EXISTS idx_judgments_org_id ON public.judgments(org_id)';
END IF;
END IF;
-- Check if plaintiffs table exists
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiffs'
) THEN EXECUTE $sql$COMMENT ON TABLE public.plaintiffs IS '{"description": "Plaintiff master records", "sensitivity": "HIGH", "contains_pii": true}' $sql$;
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiffs'
        AND column_name = 'org_id'
) THEN EXECUTE 'ALTER TABLE public.plaintiffs ADD COLUMN org_id UUID REFERENCES tenant.orgs(id)';
EXECUTE 'CREATE INDEX IF NOT EXISTS idx_plaintiffs_org_id ON public.plaintiffs(org_id)';
END IF;
END IF;
-- Check if plaintiff_contacts table exists
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
) THEN EXECUTE $sql$COMMENT ON TABLE public.plaintiff_contacts IS '{"description": "Plaintiff contact records", "sensitivity": "HIGH", "contains_pii": true}' $sql$;
END IF;
END $$;
-- ============================================================================
-- PART 4: Row Level Security Setup (Conditional)
-- ============================================================================
-- Note: RLS is enabled conditionally only if tables exist
DO $$ BEGIN -- Enable RLS on judgments if exists
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
) THEN EXECUTE 'ALTER TABLE public.judgments ENABLE ROW LEVEL SECURITY';
EXECUTE 'ALTER TABLE public.judgments FORCE ROW LEVEL SECURITY';
-- Drop and recreate policies
EXECUTE 'DROP POLICY IF EXISTS "judgments_org_isolation" ON public.judgments';
EXECUTE 'DROP POLICY IF EXISTS "judgments_service_role_bypass" ON public.judgments';
EXECUTE $policy$ CREATE POLICY "judgments_org_isolation" ON public.judgments FOR ALL USING (
    org_id IS NULL
    OR org_id IN (
        SELECT tenant.user_org_ids()
    )
) $policy$;
EXECUTE $policy$ CREATE POLICY "judgments_service_role_bypass" ON public.judgments FOR ALL TO service_role USING (true) WITH CHECK (true) $policy$;
END IF;
-- Enable RLS on plaintiffs if exists
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiffs'
) THEN EXECUTE 'ALTER TABLE public.plaintiffs ENABLE ROW LEVEL SECURITY';
EXECUTE 'ALTER TABLE public.plaintiffs FORCE ROW LEVEL SECURITY';
EXECUTE 'DROP POLICY IF EXISTS "plaintiffs_org_isolation" ON public.plaintiffs';
EXECUTE 'DROP POLICY IF EXISTS "plaintiffs_service_role_bypass" ON public.plaintiffs';
EXECUTE $policy$ CREATE POLICY "plaintiffs_org_isolation" ON public.plaintiffs FOR ALL USING (
    org_id IS NULL
    OR org_id IN (
        SELECT tenant.user_org_ids()
    )
) $policy$;
EXECUTE $policy$ CREATE POLICY "plaintiffs_service_role_bypass" ON public.plaintiffs FOR ALL TO service_role USING (true) WITH CHECK (true) $policy$;
END IF;
-- Enable RLS on plaintiff_contacts if exists
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
) THEN EXECUTE 'ALTER TABLE public.plaintiff_contacts ENABLE ROW LEVEL SECURITY';
EXECUTE 'ALTER TABLE public.plaintiff_contacts FORCE ROW LEVEL SECURITY';
EXECUTE 'DROP POLICY IF EXISTS "plaintiff_contacts_org_isolation" ON public.plaintiff_contacts';
EXECUTE 'DROP POLICY IF EXISTS "plaintiff_contacts_service_role_bypass" ON public.plaintiff_contacts';
EXECUTE $policy$ CREATE POLICY "plaintiff_contacts_org_isolation" ON public.plaintiff_contacts FOR ALL USING (
    EXISTS (
        SELECT 1
        FROM public.plaintiffs p
        WHERE p.id = plaintiff_contacts.plaintiff_id
            AND (
                p.org_id IS NULL
                OR p.org_id IN (
                    SELECT tenant.user_org_ids()
                )
            )
    )
) $policy$;
EXECUTE $policy$ CREATE POLICY "plaintiff_contacts_service_role_bypass" ON public.plaintiff_contacts FOR ALL TO service_role USING (true) WITH CHECK (true) $policy$;
END IF;
END $$;
-- ============================================================================
-- Migration Complete
-- ============================================================================
