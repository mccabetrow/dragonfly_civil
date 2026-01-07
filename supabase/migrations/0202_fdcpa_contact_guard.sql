-- ============================================================================
-- 0202_fdcpa_contact_guard.sql
-- FDCPA Contact Time Guard: Enforce legal contact windows for debt collection
-- ============================================================================
--
-- PURPOSE:
--   The Fair Debt Collection Practices Act (FDCPA) prohibits contacting
--   consumers before 8:00 AM or after 9:00 PM in the consumer's local time.
--   This migration provides:
--     1. A function to check if a given time is within the FDCPA window
--     2. A communications log table with a CHECK constraint enforcing the rule
--
-- USAGE:
--   n8n workflows should:
--     1. Call fn_is_fdcpa_allowed_time() BEFORE sending any outbound message
--     2. Insert a row into public.communications AFTER sending, which serves
--        as a second line of defense (the CHECK constraint will reject
--        any outbound message sent outside the FDCPA window)
--
-- SAFE PATTERNS:
--   - CREATE OR REPLACE FUNCTION
--   - CREATE TABLE IF NOT EXISTS
--   - DROP POLICY IF EXISTS before CREATE POLICY
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- EXTENSION: Ensure uuid-ossp is available
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- ============================================================================
-- FUNCTION: public.fn_is_fdcpa_allowed_time
-- ============================================================================
-- Checks if a given timestamp falls within the FDCPA-allowed contact window
-- (8:00 AM to 9:00 PM) in the debtor's local timezone.
--
-- PARAMETERS:
--   _ts: The timestamp to check (typically the current time or scheduled send time)
--   _debtor_timezone: IANA timezone string (e.g., 'America/New_York', 'America/Chicago')
--                     If NULL, defaults to 'America/New_York' (conservative for NY-based firm)
--
-- RETURNS:
--   TRUE if the time is within 08:00:00 to 20:59:59 local time
--   FALSE if outside the FDCPA window (before 8 AM or at/after 9 PM)
--
-- USAGE FROM n8n:
--   SELECT public.fn_is_fdcpa_allowed_time(now(), 'America/New_York');
--   -- Returns TRUE if current time is between 8 AM and 9 PM in New York
-- ============================================================================
CREATE OR REPLACE FUNCTION public.fn_is_fdcpa_allowed_time(
        _ts timestamptz,
        _debtor_timezone text
    ) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE local_time time;
BEGIN -- Convert the timestamp to local time in the debtor's timezone
-- If timezone is null or empty, default to America/New_York
local_time := (
    _ts AT TIME ZONE COALESCE(
        NULLIF(TRIM(_debtor_timezone), ''),
        'America/New_York'
    )
)::time;
-- FDCPA window: 08:00:00 <= local_time < 21:00:00
-- This means contacts are allowed from 8:00:00.000 through 20:59:59.999
RETURN local_time >= time '08:00:00'
AND local_time < time '21:00:00';
END;
$$;
COMMENT ON FUNCTION public.fn_is_fdcpa_allowed_time IS 'Checks if a timestamp falls within the FDCPA-allowed contact window (8 AM to 9 PM) in debtor local timezone. Params: _ts (timestamptz), _debtor_timezone (IANA, defaults to America/New_York). Returns TRUE if contact allowed. n8n MUST call BEFORE sending outbound messages.';
-- Grant execute to service_role (workers/n8n) and authenticated (dashboards)
GRANT EXECUTE ON FUNCTION public.fn_is_fdcpa_allowed_time(timestamptz, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_is_fdcpa_allowed_time(timestamptz, text) TO authenticated;
-- ============================================================================
-- TABLE: public.communications
-- ============================================================================
-- Log of all communications (outbound and inbound) with debtors.
-- The CHECK constraint enforces FDCPA time window for outbound messages
-- as a database-level safeguard.
--
-- IMPORTANT:
--   - n8n should check fn_is_fdcpa_allowed_time() BEFORE sending
--   - n8n should INSERT into this table AFTER sending
--   - The CHECK constraint is a second line of defense; if a bug in n8n
--     tries to log an outbound message sent outside the FDCPA window,
--     the INSERT will fail
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.communications (
    -- Primary key
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Link to the judgment (required for audit trail)
    judgment_id uuid REFERENCES public.core_judgments(id) ON DELETE CASCADE,
    -- Communication details
    channel text NOT NULL,
    -- 'sms', 'email', 'phone', 'mail', 'other'
    direction text NOT NULL,
    -- 'outbound', 'inbound'
    -- Timing
    sent_at timestamptz NOT NULL DEFAULT now(),
    -- Debtor's timezone for FDCPA compliance checking
    -- IANA timezone string, e.g., 'America/New_York', 'America/Chicago'
    debtor_timezone text,
    -- Message content (may be redacted for sensitive data)
    body text,
    -- FDCPA Contact Time Constraint
    -- For OUTBOUND communications only, enforce that sent_at is within
    -- the FDCPA-allowed window (8 AM - 9 PM debtor local time).
    -- INBOUND messages are not restricted.
    CONSTRAINT communications_fdcpa_time_check CHECK (
        direction <> 'outbound'
        OR public.fn_is_fdcpa_allowed_time(sent_at, debtor_timezone)
    ),
    -- Validate channel values
    CONSTRAINT communications_channel_check CHECK (
        channel IN ('sms', 'email', 'phone', 'mail', 'other')
    ),
    -- Validate direction values
    CONSTRAINT communications_direction_check CHECK (
        direction IN ('outbound', 'inbound')
    )
);
-- ============================================================================
-- INDEXES
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_communications_judgment_id ON public.communications(judgment_id);
CREATE INDEX IF NOT EXISTS idx_communications_sent_at ON public.communications(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_communications_channel ON public.communications(channel);
CREATE INDEX IF NOT EXISTS idx_communications_direction ON public.communications(direction);
-- Composite index for common query: judgment + time range
CREATE INDEX IF NOT EXISTS idx_communications_judgment_sent ON public.communications(judgment_id, sent_at DESC);
-- ============================================================================
-- COMMENTS
-- ============================================================================
COMMENT ON TABLE public.communications IS 'Log of all communications with debtors. FDCPA CHECK constraint prevents outbound messages outside 8 AM - 9 PM debtor local time. n8n should call fn_is_fdcpa_allowed_time() BEFORE sending, then INSERT here as second line of defense.';
COMMENT ON COLUMN public.communications.judgment_id IS 'Reference to the judgment this communication relates to.';
COMMENT ON COLUMN public.communications.channel IS 'Communication channel: sms, email, phone, mail, or other.';
COMMENT ON COLUMN public.communications.direction IS 'Direction of communication: outbound (to debtor) or inbound (from debtor).';
COMMENT ON COLUMN public.communications.sent_at IS 'Timestamp when the message was sent (outbound) or received (inbound).';
COMMENT ON COLUMN public.communications.debtor_timezone IS 'IANA timezone of the debtor (e.g., America/New_York). Used for FDCPA compliance.';
COMMENT ON COLUMN public.communications.body IS 'Message content. May be redacted or summarized for sensitive communications.';
COMMENT ON CONSTRAINT communications_fdcpa_time_check ON public.communications IS 'FDCPA safeguard: Outbound messages must be between 8 AM and 9 PM debtor local time. Rejects INSERT outside legal window.';
-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
ALTER TABLE public.communications ENABLE ROW LEVEL SECURITY;
-- Drop existing policies for idempotency
DROP POLICY IF EXISTS communications_select_authenticated ON public.communications;
DROP POLICY IF EXISTS communications_insert_service ON public.communications;
-- Allow authenticated users to read communications log
CREATE POLICY communications_select_authenticated ON public.communications FOR
SELECT USING (auth.role() IN ('authenticated', 'service_role'));
-- Allow only service_role to insert new communications
-- (Workers and n8n use service_role credentials)
CREATE POLICY communications_insert_service ON public.communications FOR
INSERT WITH CHECK (auth.role() = 'service_role');
-- NOTE: No UPDATE or DELETE policies.
-- Communications log is append-only for audit purposes.
-- ============================================================================
-- GRANTS
-- ============================================================================
REVOKE ALL ON public.communications
FROM PUBLIC;
REVOKE ALL ON public.communications
FROM anon;
-- authenticated can only SELECT
GRANT SELECT ON public.communications TO authenticated;
-- service_role can SELECT and INSERT (not UPDATE/DELETE due to RLS)
GRANT SELECT,
    INSERT ON public.communications TO service_role;
-- ============================================================================
-- RELOAD POSTGREST SCHEMA CACHE
-- ============================================================================
SELECT public.pgrst_reload();
COMMIT;
-- ============================================================================
-- END OF MIGRATION
-- ============================================================================
