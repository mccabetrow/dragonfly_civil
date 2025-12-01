-- 0067_spawn_enforcement_flow_stub.sql
-- Provide a stub enforcement flow RPC so demo workers can acknowledge jobs safely.

-- migrate:up

CREATE OR REPLACE FUNCTION public.spawn_enforcement_flow(
    case_number text,
    template_code text
) RETURNS text []
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, judgments
AS $$
BEGIN
    -- Stub implementation for Phase 1: return an empty list of task identifiers.
    PERFORM 1;
    RETURN ARRAY[]::text[];
END;
$$;

GRANT EXECUTE ON FUNCTION public.spawn_enforcement_flow(
    text, text
) TO service_role;
GRANT EXECUTE ON FUNCTION public.spawn_enforcement_flow(
    text, text
) TO authenticated;
GRANT EXECUTE ON FUNCTION public.spawn_enforcement_flow(text, text) TO anon;

-- migrate:down

REVOKE EXECUTE ON FUNCTION public.spawn_enforcement_flow(text, text) FROM anon;
REVOKE EXECUTE ON FUNCTION public.spawn_enforcement_flow(
    text, text
) FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.spawn_enforcement_flow(
    text, text
) FROM service_role;

DROP FUNCTION IF EXISTS public.spawn_enforcement_flow (text, text);
