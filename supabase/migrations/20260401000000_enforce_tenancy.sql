-- ============================================================================
-- Migration: Enforce Strict Multi-Tenancy
-- Purpose: Backfill orphans, enforce NOT NULL on org_id, harden RLS policies
-- Date: 2026-04-01
-- Author: Principal Database Architect
-- ============================================================================
--
-- SECURITY REMEDIATION
-- ====================
-- This migration closes a critical security gap where org_id could be NULL,
-- allowing records to be visible across all tenants.
--
-- Steps:
--   1. Create Default Organization (for backfilling legacy data)
--   2. Backfill all NULL org_id records to the default org
--   3. Enforce NOT NULL constraints on all org_id columns
--   4. Rewrite RLS policies to STRICTLY require org_id matches
--
-- IMPORTANT: This migration is IRREVERSIBLE. Test thoroughly before prod.
-- ============================================================================
BEGIN;
-- ============================================================================
-- STEP 1: Ensure Default Organization Exists
-- ============================================================================
-- Create a sentinel organization for legacy/orphan data.
-- This allows us to enforce NOT NULL without losing historical records.
DO $$
DECLARE v_default_org_id UUID;
v_default_org_slug TEXT := 'dragonfly-default-org';
BEGIN -- Check if default org already exists
SELECT id INTO v_default_org_id
FROM tenant.orgs
WHERE slug = v_default_org_slug;
-- Create if not exists
IF v_default_org_id IS NULL THEN
INSERT INTO tenant.orgs (name, slug)
VALUES (
        'Default Organization (Legacy)',
        v_default_org_slug
    )
RETURNING id INTO v_default_org_id;
RAISE NOTICE '✅ Created default organization: % (ID: %)',
v_default_org_slug,
v_default_org_id;
ELSE RAISE NOTICE 'ℹ️ Default organization already exists: % (ID: %)',
v_default_org_slug,
v_default_org_id;
END IF;
-- Store the default org ID for later use
PERFORM set_config(
    'app.default_org_id',
    v_default_org_id::text,
    true
);
END $$;
-- ============================================================================
-- STEP 2: Backfill Orphan Records
-- ============================================================================
-- Assign all NULL org_id records to the default organization.
-- This preserves data integrity while enabling strict constraints.
DO $$
DECLARE v_default_org_id UUID;
v_count INTEGER;
BEGIN v_default_org_id := current_setting('app.default_org_id')::UUID;
-- -------------------------------------------------------------------------
-- public.plaintiffs
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiffs'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiffs'
        AND column_name = 'org_id'
) THEN
UPDATE public.plaintiffs
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % plaintiffs with default org_id',
v_count;
END IF;
END IF;
END IF;
-- -------------------------------------------------------------------------
-- public.judgments
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'org_id'
) THEN
UPDATE public.judgments
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % judgments with default org_id',
v_count;
END IF;
END IF;
END IF;
-- -------------------------------------------------------------------------
-- public.cases
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'cases'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'cases'
        AND column_name = 'org_id'
) THEN
UPDATE public.cases
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % cases with default org_id',
v_count;
END IF;
END IF;
END IF;
-- -------------------------------------------------------------------------
-- public.parties
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'parties'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'parties'
        AND column_name = 'org_id'
) THEN
UPDATE public.parties
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % parties with default org_id',
v_count;
END IF;
END IF;
END IF;
-- -------------------------------------------------------------------------
-- public.tasks
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'tasks'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'tasks'
        AND column_name = 'org_id'
) THEN
UPDATE public.tasks
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % tasks with default org_id',
v_count;
END IF;
END IF;
END IF;
-- -------------------------------------------------------------------------
-- public.events
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'events'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'events'
        AND column_name = 'org_id'
) THEN
UPDATE public.events
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % events with default org_id',
v_count;
END IF;
END IF;
END IF;
-- -------------------------------------------------------------------------
-- audit.event_log (special handling - normally immutable, but this is a remediation)
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'audit'
        AND table_name = 'event_log'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'audit'
        AND table_name = 'event_log'
        AND column_name = 'org_id'
) THEN -- Temporarily grant UPDATE for remediation (audit log is normally immutable)
-- This is a one-time fix for legacy data
UPDATE audit.event_log
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % audit.event_log entries with default org_id',
v_count;
END IF;
END IF;
END IF;
-- -------------------------------------------------------------------------
-- evidence.files
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'evidence'
        AND table_name = 'files'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'evidence'
        AND table_name = 'files'
        AND column_name = 'org_id'
) THEN
UPDATE evidence.files
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % evidence.files with default org_id',
v_count;
END IF;
END IF;
END IF;
-- -------------------------------------------------------------------------
-- legal.consents
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'legal'
        AND table_name = 'consents'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'legal'
        AND table_name = 'consents'
        AND column_name = 'org_id'
) THEN
UPDATE legal.consents
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % legal.consents with default org_id',
v_count;
END IF;
END IF;
END IF;
-- -------------------------------------------------------------------------
-- public.plaintiff_contacts (inherits org context from plaintiffs)
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
        AND column_name = 'org_id'
) THEN
UPDATE public.plaintiff_contacts
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % plaintiff_contacts with default org_id',
v_count;
END IF;
END IF;
END IF;
-- -------------------------------------------------------------------------
-- public.case_parties
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'case_parties'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'case_parties'
        AND column_name = 'org_id'
) THEN
UPDATE public.case_parties
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % case_parties with default org_id',
v_count;
END IF;
END IF;
END IF;
-- -------------------------------------------------------------------------
-- public.case_state
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'case_state'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'case_state'
        AND column_name = 'org_id'
) THEN
UPDATE public.case_state
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % case_state with default org_id',
v_count;
END IF;
END IF;
END IF;
-- -------------------------------------------------------------------------
-- public.playbooks
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'playbooks'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'playbooks'
        AND column_name = 'org_id'
) THEN
UPDATE public.playbooks
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % playbooks with default org_id',
v_count;
END IF;
END IF;
END IF;
-- -------------------------------------------------------------------------
-- public.playbook_executions
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'playbook_executions'
) THEN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'playbook_executions'
        AND column_name = 'org_id'
) THEN
UPDATE public.playbook_executions
SET org_id = v_default_org_id
WHERE org_id IS NULL;
GET DIAGNOSTICS v_count = ROW_COUNT;
IF v_count > 0 THEN RAISE NOTICE '✅ Backfilled % playbook_executions with default org_id',
v_count;
END IF;
END IF;
END IF;
END $$;
-- ============================================================================
-- STEP 3: Enforce NOT NULL Constraints
-- ============================================================================
-- Now that all records have org_id values, we can safely add NOT NULL.
-- This prevents future NULL org_id insertions.
DO $$ BEGIN -- -------------------------------------------------------------------------
-- public.plaintiffs
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiffs'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE public.plaintiffs
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on public.plaintiffs.org_id';
END IF;
-- -------------------------------------------------------------------------
-- public.judgments
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE public.judgments
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on public.judgments.org_id';
END IF;
-- -------------------------------------------------------------------------
-- public.cases
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'cases'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE public.cases
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on public.cases.org_id';
END IF;
-- -------------------------------------------------------------------------
-- public.parties
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'parties'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE public.parties
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on public.parties.org_id';
END IF;
-- -------------------------------------------------------------------------
-- public.tasks
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'tasks'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE public.tasks
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on public.tasks.org_id';
END IF;
-- -------------------------------------------------------------------------
-- public.events
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'events'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE public.events
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on public.events.org_id';
END IF;
-- -------------------------------------------------------------------------
-- audit.event_log
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'audit'
        AND table_name = 'event_log'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE audit.event_log
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on audit.event_log.org_id';
END IF;
-- -------------------------------------------------------------------------
-- evidence.files
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'evidence'
        AND table_name = 'files'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE evidence.files
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on evidence.files.org_id';
END IF;
-- -------------------------------------------------------------------------
-- legal.consents
-- -------------------------------------------------------------------------
-- Note: Already NOT NULL in schema, but verify
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'legal'
        AND table_name = 'consents'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE legal.consents
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on legal.consents.org_id';
END IF;
-- -------------------------------------------------------------------------
-- public.plaintiff_contacts
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE public.plaintiff_contacts
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on public.plaintiff_contacts.org_id';
END IF;
-- -------------------------------------------------------------------------
-- public.case_parties
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'case_parties'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE public.case_parties
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on public.case_parties.org_id';
END IF;
-- -------------------------------------------------------------------------
-- public.case_state
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'case_state'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE public.case_state
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on public.case_state.org_id';
END IF;
-- -------------------------------------------------------------------------
-- public.playbooks
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'playbooks'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE public.playbooks
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on public.playbooks.org_id';
END IF;
-- -------------------------------------------------------------------------
-- public.playbook_executions
-- -------------------------------------------------------------------------
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'playbook_executions'
        AND column_name = 'org_id'
        AND is_nullable = 'YES'
) THEN
ALTER TABLE public.playbook_executions
ALTER COLUMN org_id
SET NOT NULL;
RAISE NOTICE '🔒 Enforced NOT NULL on public.playbook_executions.org_id';
END IF;
END $$;
-- ============================================================================
-- STEP 4: RLS Policy Hardening
-- ============================================================================
-- Rewrite all RLS policies to STRICTLY require org_id membership.
-- Remove any "OR org_id IS NULL" conditions.
-- Service role bypass is handled via PostgreSQL's BYPASSRLS attribute.
-- -----------------------------------------------------------------------------
-- public.plaintiffs - STRICT org isolation
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiffs'
) THEN -- Drop legacy permissive policies
DROP POLICY IF EXISTS "plaintiffs_org_isolation" ON public.plaintiffs;
DROP POLICY IF EXISTS "plaintiffs_service_role_bypass" ON public.plaintiffs;
-- Create strict isolation policy (no NULL fallback)
CREATE POLICY "plaintiffs_strict_org_isolation" ON public.plaintiffs FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
) WITH CHECK (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
-- Service role bypass policy (explicit)
CREATE POLICY "plaintiffs_service_role_access" ON public.plaintiffs FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on public.plaintiffs';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- public.judgments - STRICT org isolation
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
) THEN DROP POLICY IF EXISTS "judgments_org_isolation" ON public.judgments;
DROP POLICY IF EXISTS "judgments_service_role_bypass" ON public.judgments;
CREATE POLICY "judgments_strict_org_isolation" ON public.judgments FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
) WITH CHECK (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
CREATE POLICY "judgments_service_role_access" ON public.judgments FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on public.judgments';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- public.cases - STRICT org isolation
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'cases'
) THEN DROP POLICY IF EXISTS "cases_org_isolation" ON public.cases;
DROP POLICY IF EXISTS "cases_service_role_bypass" ON public.cases;
CREATE POLICY "cases_strict_org_isolation" ON public.cases FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
) WITH CHECK (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
CREATE POLICY "cases_service_role_access" ON public.cases FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on public.cases';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- public.parties - STRICT org isolation
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'parties'
) THEN DROP POLICY IF EXISTS "parties_org_isolation" ON public.parties;
DROP POLICY IF EXISTS "parties_service_role_bypass" ON public.parties;
CREATE POLICY "parties_strict_org_isolation" ON public.parties FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
) WITH CHECK (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
CREATE POLICY "parties_service_role_access" ON public.parties FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on public.parties';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- public.tasks - STRICT org isolation
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'tasks'
) THEN DROP POLICY IF EXISTS "tasks_org_isolation" ON public.tasks;
DROP POLICY IF EXISTS "tasks_service_role_bypass" ON public.tasks;
CREATE POLICY "tasks_strict_org_isolation" ON public.tasks FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
) WITH CHECK (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
CREATE POLICY "tasks_service_role_access" ON public.tasks FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on public.tasks';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- public.events - STRICT org isolation (guarded on org_id column)
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'events'
) THEN RETURN;
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'events'
        AND column_name = 'org_id'
) THEN RAISE NOTICE '⚠ Skipping events RLS - org_id column does not exist';
-- Still create service_role bypass policy
DROP POLICY IF EXISTS "events_service_role_bypass" ON public.events;
CREATE POLICY "events_service_role_access" ON public.events FOR ALL TO service_role USING (true) WITH CHECK (true);
RETURN;
END IF;
DROP POLICY IF EXISTS "events_org_isolation" ON public.events;
DROP POLICY IF EXISTS "events_service_role_bypass" ON public.events;
CREATE POLICY "events_strict_org_isolation" ON public.events FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
) WITH CHECK (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
CREATE POLICY "events_service_role_access" ON public.events FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on public.events';
END $$;
-- -----------------------------------------------------------------------------
-- public.plaintiff_contacts - STRICT org isolation (via parent plaintiffs)
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
) THEN DROP POLICY IF EXISTS "plaintiff_contacts_org_isolation" ON public.plaintiff_contacts;
DROP POLICY IF EXISTS "plaintiff_contacts_service_role_bypass" ON public.plaintiff_contacts;
-- Check if org_id column exists (might inherit via FK)
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
        AND column_name = 'org_id'
) THEN CREATE POLICY "plaintiff_contacts_strict_org_isolation" ON public.plaintiff_contacts FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
) WITH CHECK (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
ELSE -- If no org_id, use join through plaintiffs
CREATE POLICY "plaintiff_contacts_strict_org_isolation" ON public.plaintiff_contacts FOR ALL USING (
    plaintiff_id IN (
        SELECT id
        FROM public.plaintiffs
        WHERE org_id IN (
                SELECT tenant.user_org_ids()
            )
    )
);
END IF;
CREATE POLICY "plaintiff_contacts_service_role_access" ON public.plaintiff_contacts FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on public.plaintiff_contacts';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- public.case_parties - STRICT org isolation
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'case_parties'
) THEN DROP POLICY IF EXISTS "case_parties_org_isolation" ON public.case_parties;
DROP POLICY IF EXISTS "case_parties_service_role_bypass" ON public.case_parties;
CREATE POLICY "case_parties_strict_org_isolation" ON public.case_parties FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
) WITH CHECK (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
CREATE POLICY "case_parties_service_role_access" ON public.case_parties FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on public.case_parties';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- public.case_state - STRICT org isolation
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'case_state'
) THEN DROP POLICY IF EXISTS "case_state_org_isolation" ON public.case_state;
DROP POLICY IF EXISTS "case_state_service_role_bypass" ON public.case_state;
CREATE POLICY "case_state_strict_org_isolation" ON public.case_state FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
) WITH CHECK (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
CREATE POLICY "case_state_service_role_access" ON public.case_state FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on public.case_state';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- public.playbooks - STRICT org isolation
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'playbooks'
) THEN DROP POLICY IF EXISTS "playbooks_org_isolation" ON public.playbooks;
DROP POLICY IF EXISTS "playbooks_service_role_bypass" ON public.playbooks;
CREATE POLICY "playbooks_strict_org_isolation" ON public.playbooks FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
) WITH CHECK (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
CREATE POLICY "playbooks_service_role_access" ON public.playbooks FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on public.playbooks';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- public.playbook_executions - STRICT org isolation
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'playbook_executions'
) THEN DROP POLICY IF EXISTS "playbook_exec_org_isolation" ON public.playbook_executions;
DROP POLICY IF EXISTS "playbook_executions_service_role_bypass" ON public.playbook_executions;
CREATE POLICY "playbook_executions_strict_org_isolation" ON public.playbook_executions FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
) WITH CHECK (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
CREATE POLICY "playbook_executions_service_role_access" ON public.playbook_executions FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on public.playbook_executions';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- audit.event_log - STRICT org isolation (read-only for users)
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'audit'
        AND table_name = 'event_log'
) THEN DROP POLICY IF EXISTS "event_log_org_isolation" ON audit.event_log;
DROP POLICY IF EXISTS "event_log_service_role_bypass" ON audit.event_log;
-- Users can only SELECT their org's audit logs
CREATE POLICY "event_log_strict_org_isolation" ON audit.event_log FOR
SELECT USING (
        org_id IN (
            SELECT tenant.user_org_ids()
        )
    );
-- Service role has full access (for audit writes)
CREATE POLICY "event_log_service_role_access" ON audit.event_log FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on audit.event_log';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- evidence.files - STRICT org isolation
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'evidence'
        AND table_name = 'files'
) THEN DROP POLICY IF EXISTS "evidence_files_org_isolation" ON evidence.files;
DROP POLICY IF EXISTS "evidence_files_service_role_bypass" ON evidence.files;
CREATE POLICY "evidence_files_strict_org_isolation" ON evidence.files FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
) WITH CHECK (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
CREATE POLICY "evidence_files_service_role_access" ON evidence.files FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on evidence.files';
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- legal.consents - STRICT org isolation
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'legal'
        AND table_name = 'consents'
) THEN DROP POLICY IF EXISTS "consents_org_isolation" ON legal.consents;
DROP POLICY IF EXISTS "consents_service_role_bypass" ON legal.consents;
CREATE POLICY "consents_strict_org_isolation" ON legal.consents FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
) WITH CHECK (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
CREATE POLICY "consents_service_role_access" ON legal.consents FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '🛡️ Hardened RLS on legal.consents';
END IF;
END $$;
-- ============================================================================
-- STEP 5: Verification & Audit Log
-- ============================================================================
-- Log this security remediation action
DO $$
DECLARE v_default_org_id UUID;
BEGIN v_default_org_id := current_setting('app.default_org_id', true)::UUID;
-- Log the remediation to audit
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'audit'
        AND table_name = 'event_log'
) THEN
INSERT INTO audit.event_log (
        actor_type,
        action,
        entity_type,
        entity_id,
        changes,
        org_id
    )
VALUES (
        'system',
        'tenancy.enforced',
        'migration',
        NULL,
        jsonb_build_object(
            'migration',
            '20260401000000_enforce_tenancy',
            'default_org_id',
            v_default_org_id,
            'timestamp',
            now(),
            'actions',
            ARRAY [
                    'created_default_org',
                    'backfilled_orphans',
                    'enforced_not_null',
                    'hardened_rls_policies'
                ]
        ),
        v_default_org_id
    );
END IF;
RAISE NOTICE '============================================================';
RAISE NOTICE '✅ TENANCY ENFORCEMENT COMPLETE';
RAISE NOTICE '============================================================';
RAISE NOTICE '  Default Org ID: %',
v_default_org_id;
RAISE NOTICE '  All org_id columns now NOT NULL';
RAISE NOTICE '  All RLS policies strictly enforce org membership';
RAISE NOTICE '  Service role retains full access';
RAISE NOTICE '============================================================';
END $$;
COMMIT;
-- ============================================================================
-- POST-MIGRATION VERIFICATION QUERIES
-- ============================================================================
-- Run these manually to verify the migration worked:
--
-- 1. Check no NULL org_id values remain:
--    SELECT 'plaintiffs' as tbl, count(*) FROM public.plaintiffs WHERE org_id IS NULL
--    UNION ALL SELECT 'judgments', count(*) FROM public.judgments WHERE org_id IS NULL
--    UNION ALL SELECT 'cases', count(*) FROM public.cases WHERE org_id IS NULL;
--
-- 2. Verify NOT NULL constraints:
--    SELECT table_schema, table_name, column_name, is_nullable
--    FROM information_schema.columns
--    WHERE column_name = 'org_id'
--    AND table_schema IN ('public', 'audit', 'evidence', 'legal')
--    ORDER BY table_schema, table_name;
--
-- 3. List all RLS policies:
--    SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual
--    FROM pg_policies
--    WHERE policyname LIKE '%org%'
--    ORDER BY schemaname, tablename;
-- ============================================================================