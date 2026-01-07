-- ============================================================================
-- Migration: State Engine
-- Purpose: Domain events, playbooks, tasks, and atomic state transitions
-- Date: 2026-01-06
-- ============================================================================
-- ============================================================================
-- PART 1: Event Type Enum
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
        JOIN pg_namespace n ON t.typnamespace = n.oid
    WHERE t.typname = 'event_type'
        AND n.nspname = 'public'
) THEN CREATE TYPE public.event_type AS ENUM (
    'stage_changed',
    'status_changed',
    'case_created',
    'case_closed',
    'party_added',
    'party_removed',
    'task_created',
    'task_completed',
    'document_attached',
    'payment_received',
    'note_added',
    'assignment_changed',
    'priority_changed',
    'hold_placed',
    'hold_released',
    'playbook_triggered',
    'custom'
);
END IF;
END $$;
-- ============================================================================
-- PART 2: Task Status Enum
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'task_status'
) THEN CREATE TYPE public.task_status AS ENUM (
    'pending',
    'in_progress',
    'completed',
    'cancelled',
    'blocked',
    'deferred'
);
END IF;
END $$;
-- ============================================================================
-- PART 3: Task Priority Enum
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'task_priority'
) THEN CREATE TYPE public.task_priority AS ENUM (
    'low',
    'normal',
    'high',
    'urgent'
);
END IF;
END $$;
-- ============================================================================
-- PART 4: Domain Events Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES tenant.orgs(id),
    case_id UUID NOT NULL REFERENCES public.cases(id) ON DELETE CASCADE,
    type public.event_type NOT NULL,
    subtype TEXT,
    payload JSONB NOT NULL DEFAULT '{}',
    created_by UUID,
    created_by_type TEXT NOT NULL DEFAULT 'user',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.events IS '{"description": "Domain events for case state machine", "sensitivity": "MEDIUM", "retention": "7_years"}';
CREATE INDEX IF NOT EXISTS idx_events_case_id ON public.events(case_id);
CREATE INDEX IF NOT EXISTS idx_events_org_id ON public.events(org_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON public.events(type);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON public.events(created_at DESC);
-- ============================================================================
-- PART 5: Playbooks Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.playbooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES tenant.orgs(id),
    name TEXT NOT NULL,
    description TEXT,
    trigger_stage public.case_stage,
    trigger_event public.event_type,
    trigger_conditions JSONB DEFAULT '{}',
    tasks_template JSONB NOT NULL DEFAULT '[]',
    is_active BOOLEAN NOT NULL DEFAULT true,
    priority INTEGER NOT NULL DEFAULT 100,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_playbook_name UNIQUE (org_id, name)
);
COMMENT ON TABLE public.playbooks IS '{"description": "Workflow automation playbooks triggered by stage/events", "sensitivity": "LOW"}';
CREATE INDEX IF NOT EXISTS idx_playbooks_org_id ON public.playbooks(org_id);
CREATE INDEX IF NOT EXISTS idx_playbooks_trigger_stage ON public.playbooks(trigger_stage)
WHERE trigger_stage IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_playbooks_active ON public.playbooks(is_active)
WHERE is_active = true;
-- ============================================================================
-- PART 6: Tasks Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES tenant.orgs(id),
    case_id UUID NOT NULL REFERENCES public.cases(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    status public.task_status NOT NULL DEFAULT 'pending',
    priority public.task_priority NOT NULL DEFAULT 'normal',
    assigned_to UUID,
    assigned_role TEXT,
    due_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    playbook_id UUID REFERENCES public.playbooks(id),
    parent_task_id UUID REFERENCES public.tasks(id),
    result TEXT,
    result_data JSONB,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.tasks IS '{"description": "Case tasks and action items", "sensitivity": "MEDIUM"}';
CREATE INDEX IF NOT EXISTS idx_tasks_case_id ON public.tasks(case_id);
CREATE INDEX IF NOT EXISTS idx_tasks_org_id ON public.tasks(org_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON public.tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON public.tasks(assigned_to)
WHERE assigned_to IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_due_at ON public.tasks(due_at)
WHERE due_at IS NOT NULL;
-- ============================================================================
-- PART 7: Playbook Execution Log
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.playbook_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES tenant.orgs(id),
    playbook_id UUID NOT NULL REFERENCES public.playbooks(id),
    case_id UUID NOT NULL REFERENCES public.cases(id) ON DELETE CASCADE,
    trigger_event_id UUID REFERENCES public.events(id),
    status TEXT NOT NULL DEFAULT 'pending',
    tasks_created INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'
);
COMMENT ON TABLE public.playbook_executions IS '{"description": "Log of playbook executions", "sensitivity": "LOW"}';
CREATE INDEX IF NOT EXISTS idx_playbook_exec_playbook ON public.playbook_executions(playbook_id);
CREATE INDEX IF NOT EXISTS idx_playbook_exec_case ON public.playbook_executions(case_id);
-- ============================================================================
-- PART 8: Security - Lock Down case_state Direct Access
-- ============================================================================
REVOKE
INSERT,
    UPDATE ON public.case_state
FROM authenticated;
GRANT ALL ON public.case_state TO service_role;
-- ============================================================================
-- PART 9: Auto-Update Triggers
-- ============================================================================
DROP TRIGGER IF EXISTS trg_playbooks_updated_at ON public.playbooks;
CREATE TRIGGER trg_playbooks_updated_at BEFORE
UPDATE ON public.playbooks FOR EACH ROW EXECUTE FUNCTION public.update_timestamp();
DROP TRIGGER IF EXISTS trg_tasks_updated_at ON public.tasks;
CREATE TRIGGER trg_tasks_updated_at BEFORE
UPDATE ON public.tasks FOR EACH ROW EXECUTE FUNCTION public.update_timestamp();
-- ============================================================================
-- PART 10: Row Level Security
-- ============================================================================
ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.playbooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.playbook_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.events FORCE ROW LEVEL SECURITY;
ALTER TABLE public.playbooks FORCE ROW LEVEL SECURITY;
ALTER TABLE public.tasks FORCE ROW LEVEL SECURITY;
ALTER TABLE public.playbook_executions FORCE ROW LEVEL SECURITY;
-- Events RLS
DROP POLICY IF EXISTS "events_org_isolation" ON public.events;
CREATE POLICY "events_org_isolation" ON public.events FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
DROP POLICY IF EXISTS "events_service_role_bypass" ON public.events;
CREATE POLICY "events_service_role_bypass" ON public.events FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Playbooks RLS
DROP POLICY IF EXISTS "playbooks_org_isolation" ON public.playbooks;
CREATE POLICY "playbooks_org_isolation" ON public.playbooks FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
DROP POLICY IF EXISTS "playbooks_service_role_bypass" ON public.playbooks;
CREATE POLICY "playbooks_service_role_bypass" ON public.playbooks FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Tasks RLS
DROP POLICY IF EXISTS "tasks_org_isolation" ON public.tasks;
CREATE POLICY "tasks_org_isolation" ON public.tasks FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
DROP POLICY IF EXISTS "tasks_service_role_bypass" ON public.tasks;
CREATE POLICY "tasks_service_role_bypass" ON public.tasks FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Playbook Executions RLS
DROP POLICY IF EXISTS "playbook_exec_org_isolation" ON public.playbook_executions;
CREATE POLICY "playbook_exec_org_isolation" ON public.playbook_executions FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
DROP POLICY IF EXISTS "playbook_exec_service_role_bypass" ON public.playbook_executions;
CREATE POLICY "playbook_exec_service_role_bypass" ON public.playbook_executions FOR ALL TO service_role USING (true) WITH CHECK (true);
-- ============================================================================
-- PART 11: API Schema Functions - State Transition RPCs
-- Note: These functions use the actual case_state schema (stage, is_priority, 
-- is_on_hold) and the actual audit.event_log schema (entity_type, entity_id, changes)
-- ============================================================================
-- Ensure api schema exists
CREATE SCHEMA IF NOT EXISTS api;
-- Grant usage on api schema
GRANT USAGE ON SCHEMA api TO authenticated,
    service_role;
-- ============================================================================
-- api.transition_case_stage: Atomic 3-write state transition
-- Uses: case_state.stage (not current_stage)
-- ============================================================================
CREATE OR REPLACE FUNCTION api.transition_case_stage(
        p_case_id UUID,
        p_new_stage TEXT,
        p_reason TEXT DEFAULT NULL
    ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    tenant,
    audit AS $func$
DECLARE v_org_id UUID;
v_old_stage TEXT;
v_new_stage public.case_stage;
v_event_id UUID;
v_state_updated BOOLEAN := FALSE;
v_event_created BOOLEAN := FALSE;
v_audit_logged BOOLEAN := FALSE;
BEGIN -- Validate stage value
BEGIN v_new_stage := p_new_stage::public.case_stage;
EXCEPTION
WHEN invalid_text_representation THEN RAISE EXCEPTION 'Invalid stage value: %. Valid values: intake, review, active, enforcement, payment_plan, litigation, closed, suspended',
p_new_stage;
END;
-- Get current state with lock (using actual column name: stage)
SELECT cs.org_id,
    cs.stage::TEXT INTO v_org_id,
    v_old_stage
FROM public.case_state cs
WHERE cs.case_id = p_case_id FOR
UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Case not found: %',
p_case_id;
END IF;
-- Idempotent: if already at target stage, return success
IF v_old_stage = p_new_stage THEN RETURN jsonb_build_object(
    'success',
    true,
    'case_id',
    p_case_id,
    'old_stage',
    v_old_stage,
    'new_stage',
    p_new_stage,
    'changed',
    false,
    'message',
    'Already at target stage'
);
END IF;
-- WRITE 1: Update case_state
UPDATE public.case_state
SET stage = v_new_stage,
    updated_at = now()
WHERE case_id = p_case_id;
v_state_updated := TRUE;
-- WRITE 2: Insert domain event
INSERT INTO public.events (
        org_id,
        case_id,
        type,
        subtype,
        payload,
        created_by_type
    )
VALUES (
        v_org_id,
        p_case_id,
        'stage_changed',
        'transition',
        jsonb_build_object(
            'old_stage',
            v_old_stage,
            'new_stage',
            p_new_stage,
            'reason',
            COALESCE(p_reason, 'Manual transition'),
            'timestamp',
            now()
        ),
        'system'
    )
RETURNING id INTO v_event_id;
v_event_created := TRUE;
-- WRITE 3: Insert audit log (using actual schema: entity_type, entity_id, changes)
INSERT INTO audit.event_log (
        org_id,
        entity_type,
        entity_id,
        action,
        actor_type,
        changes
    )
VALUES (
        v_org_id,
        'case',
        p_case_id,
        'stage_transition',
        'system',
        jsonb_build_object(
            'old_stage',
            v_old_stage,
            'new_stage',
            p_new_stage,
            'reason',
            p_reason
        )
    );
v_audit_logged := TRUE;
RETURN jsonb_build_object(
    'success',
    true,
    'case_id',
    p_case_id,
    'old_stage',
    v_old_stage,
    'new_stage',
    p_new_stage,
    'changed',
    true,
    'event_id',
    v_event_id,
    'invariants',
    jsonb_build_object(
        'state_updated',
        v_state_updated,
        'event_created',
        v_event_created,
        'audit_logged',
        v_audit_logged
    )
);
END;
$func$;
COMMENT ON FUNCTION api.transition_case_stage IS 'Atomic 3-write state transition: case_state + events + audit.event_log';
-- ============================================================================
-- api.update_case_status: Update status within current stage
-- ============================================================================
CREATE OR REPLACE FUNCTION api.update_case_status(
        p_case_id UUID,
        p_status TEXT,
        p_reason TEXT DEFAULT NULL
    ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    tenant,
    audit AS $func$
DECLARE v_org_id UUID;
v_old_status TEXT;
BEGIN
SELECT cs.org_id,
    cs.status INTO v_org_id,
    v_old_status
FROM public.case_state cs
WHERE cs.case_id = p_case_id FOR
UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Case not found: %',
p_case_id;
END IF;
UPDATE public.case_state
SET status = p_status,
    updated_at = now()
WHERE case_id = p_case_id;
INSERT INTO public.events (org_id, case_id, type, payload, created_by_type)
VALUES (
        v_org_id,
        p_case_id,
        'status_changed',
        jsonb_build_object(
            'old_status',
            v_old_status,
            'new_status',
            p_status,
            'reason',
            p_reason
        ),
        'system'
    );
INSERT INTO audit.event_log (
        org_id,
        entity_type,
        entity_id,
        action,
        actor_type,
        changes
    )
VALUES (
        v_org_id,
        'case',
        p_case_id,
        'status_update',
        'system',
        jsonb_build_object(
            'old_status',
            v_old_status,
            'new_status',
            p_status
        )
    );
RETURN jsonb_build_object(
    'success',
    true,
    'case_id',
    p_case_id,
    'old_status',
    v_old_status,
    'new_status',
    p_status
);
END;
$func$;
-- ============================================================================
-- api.assign_case: Assign case to user
-- ============================================================================
CREATE OR REPLACE FUNCTION api.assign_case(
        p_case_id UUID,
        p_assigned_to UUID,
        p_reason TEXT DEFAULT NULL
    ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    tenant,
    audit AS $func$
DECLARE v_org_id UUID;
v_old_assigned_to UUID;
BEGIN
SELECT cs.org_id,
    cs.assigned_to INTO v_org_id,
    v_old_assigned_to
FROM public.case_state cs
WHERE cs.case_id = p_case_id FOR
UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Case not found: %',
p_case_id;
END IF;
UPDATE public.case_state
SET assigned_to = p_assigned_to,
    assigned_at = now(),
    updated_at = now()
WHERE case_id = p_case_id;
INSERT INTO public.events (org_id, case_id, type, payload, created_by_type)
VALUES (
        v_org_id,
        p_case_id,
        'assignment_changed',
        jsonb_build_object(
            'old_assigned_to',
            v_old_assigned_to,
            'new_assigned_to',
            p_assigned_to,
            'reason',
            p_reason
        ),
        'system'
    );
INSERT INTO audit.event_log (
        org_id,
        entity_type,
        entity_id,
        action,
        actor_type,
        changes
    )
VALUES (
        v_org_id,
        'case',
        p_case_id,
        'assignment_change',
        'system',
        jsonb_build_object(
            'old_assigned_to',
            v_old_assigned_to,
            'new_assigned_to',
            p_assigned_to
        )
    );
RETURN jsonb_build_object(
    'success',
    true,
    'case_id',
    p_case_id,
    'assigned_to',
    p_assigned_to
);
END;
$func$;
-- ============================================================================
-- api.set_case_priority: Set case priority flag
-- Uses: case_state.is_priority (not priority)
-- ============================================================================
CREATE OR REPLACE FUNCTION api.set_case_priority(
        p_case_id UUID,
        p_is_priority BOOLEAN,
        p_reason TEXT DEFAULT NULL
    ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    tenant,
    audit AS $func$
DECLARE v_org_id UUID;
v_old_is_priority BOOLEAN;
BEGIN
SELECT cs.org_id,
    cs.is_priority INTO v_org_id,
    v_old_is_priority
FROM public.case_state cs
WHERE cs.case_id = p_case_id FOR
UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Case not found: %',
p_case_id;
END IF;
UPDATE public.case_state
SET is_priority = p_is_priority,
    updated_at = now()
WHERE case_id = p_case_id;
INSERT INTO public.events (org_id, case_id, type, payload, created_by_type)
VALUES (
        v_org_id,
        p_case_id,
        'priority_changed',
        jsonb_build_object(
            'old_is_priority',
            v_old_is_priority,
            'new_is_priority',
            p_is_priority,
            'reason',
            p_reason
        ),
        'system'
    );
INSERT INTO audit.event_log (
        org_id,
        entity_type,
        entity_id,
        action,
        actor_type,
        changes
    )
VALUES (
        v_org_id,
        'case',
        p_case_id,
        'priority_change',
        'system',
        jsonb_build_object(
            'old_is_priority',
            v_old_is_priority,
            'new_is_priority',
            p_is_priority
        )
    );
RETURN jsonb_build_object(
    'success',
    true,
    'case_id',
    p_case_id,
    'is_priority',
    p_is_priority
);
END;
$func$;
-- ============================================================================
-- api.set_case_hold: Place or release hold on case
-- Uses: case_state.is_on_hold (not on_hold)
-- ============================================================================
CREATE OR REPLACE FUNCTION api.set_case_hold(
        p_case_id UUID,
        p_is_on_hold BOOLEAN,
        p_hold_reason TEXT DEFAULT NULL
    ) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    tenant,
    audit AS $func$
DECLARE v_org_id UUID;
v_was_on_hold BOOLEAN;
v_event_type public.event_type;
BEGIN
SELECT cs.org_id,
    cs.is_on_hold INTO v_org_id,
    v_was_on_hold
FROM public.case_state cs
WHERE cs.case_id = p_case_id FOR
UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Case not found: %',
p_case_id;
END IF;
UPDATE public.case_state
SET is_on_hold = p_is_on_hold,
    hold_reason = CASE
        WHEN p_is_on_hold THEN p_hold_reason
        ELSE NULL
    END,
    updated_at = now()
WHERE case_id = p_case_id;
v_event_type := CASE
    WHEN p_is_on_hold THEN 'hold_placed'::public.event_type
    ELSE 'hold_released'::public.event_type
END;
INSERT INTO public.events (org_id, case_id, type, payload, created_by_type)
VALUES (
        v_org_id,
        p_case_id,
        v_event_type,
        jsonb_build_object(
            'is_on_hold',
            p_is_on_hold,
            'reason',
            p_hold_reason
        ),
        'system'
    );
INSERT INTO audit.event_log (
        org_id,
        entity_type,
        entity_id,
        action,
        actor_type,
        changes
    )
VALUES (
        v_org_id,
        'case',
        p_case_id,
        CASE
            WHEN p_is_on_hold THEN 'hold_placed'
            ELSE 'hold_released'
        END,
        'system',
        jsonb_build_object(
            'is_on_hold',
            p_is_on_hold,
            'hold_reason',
            p_hold_reason
        )
    );
RETURN jsonb_build_object(
    'success',
    true,
    'case_id',
    p_case_id,
    'is_on_hold',
    p_is_on_hold
);
END;
$func$;
-- Grant execute permissions on API functions
GRANT EXECUTE ON FUNCTION api.transition_case_stage TO authenticated,
    service_role;
GRANT EXECUTE ON FUNCTION api.update_case_status TO authenticated,
    service_role;
GRANT EXECUTE ON FUNCTION api.assign_case TO authenticated,
    service_role;
GRANT EXECUTE ON FUNCTION api.set_case_priority TO authenticated,
    service_role;
GRANT EXECUTE ON FUNCTION api.set_case_hold TO authenticated,
    service_role;
-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================