-- =============================================================================
-- Migration: Outbox Pattern for Reliable Side Effects
-- =============================================================================
-- Implements the "Transactional Outbox" pattern to ensure side effects
-- (PDF generation, emails, webhooks, external API calls) happen exactly once.
--
-- How it works:
--   1. Business transaction writes to ops.outbox within the same DB transaction
--   2. Outbox processor polls for pending messages and processes them
--   3. Successful processing marks the message as 'complete'
--   4. Failed processing increments attempts and records last_error
--   5. Messages exceeding max_attempts are moved to 'failed' status
--
-- Benefits:
--   - Side effects are durable (survive crashes)
--   - Exactly-once semantics (with idempotent processors)
--   - Decouples business logic from delivery mechanisms
--   - Provides audit trail of all external effects
-- =============================================================================
-- Create the outbox table
CREATE TABLE IF NOT EXISTS ops.outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Channel routing (which processor handles this)
    channel text NOT NULL,
    -- Payload (JSON data for the processor)
    payload jsonb NOT NULL DEFAULT '{}',
    -- Processing state
    status text NOT NULL DEFAULT 'pending',
    attempts int NOT NULL DEFAULT 0,
    max_attempts int NOT NULL DEFAULT 3,
    last_error text,
    -- Locking for concurrent processing
    locked_at timestamptz,
    locked_by text,
    -- Tracing
    correlation_id uuid,
    -- Timestamps
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    -- Constraints
    CONSTRAINT outbox_status_check CHECK (
        status IN (
            'pending',
            'processing',
            'complete',
            'failed',
            'dead_letter'
        )
    ),
    CONSTRAINT outbox_channel_check CHECK (
        channel IN (
            'pdf',
            'email',
            'webhook',
            'slack',
            'discord',
            'sms',
            'external_api'
        )
    )
);
-- Comments
COMMENT ON TABLE ops.outbox IS 'Transactional outbox for reliable side effects (exactly-once delivery)';
COMMENT ON COLUMN ops.outbox.channel IS 'Processor channel: pdf, email, webhook, slack, discord, sms, external_api';
COMMENT ON COLUMN ops.outbox.payload IS 'JSON payload with all data needed to process the message';
COMMENT ON COLUMN ops.outbox.status IS 'pending -> processing -> complete/failed -> dead_letter';
COMMENT ON COLUMN ops.outbox.locked_at IS 'Timestamp when a processor claimed this message';
COMMENT ON COLUMN ops.outbox.locked_by IS 'Worker ID that claimed this message';
COMMENT ON COLUMN ops.outbox.correlation_id IS 'End-to-end trace ID for request correlation';
-- Indexes for efficient polling
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON ops.outbox(channel, created_at)
WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_outbox_stale_locks ON ops.outbox(locked_at)
WHERE status = 'processing'
    AND locked_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_outbox_correlation ON ops.outbox(correlation_id)
WHERE correlation_id IS NOT NULL;
-- =============================================================================
-- Outbox Helper Functions
-- =============================================================================
-- Claim a batch of pending messages for processing
CREATE OR REPLACE FUNCTION ops.claim_outbox_messages(
        p_channel text,
        p_worker_id text,
        p_batch_size int DEFAULT 10,
        p_lock_timeout_minutes int DEFAULT 5
    ) RETURNS SETOF ops.outbox LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,
    ops AS $$
DECLARE v_lock_timeout interval;
BEGIN v_lock_timeout := (p_lock_timeout_minutes || ' minutes')::interval;
-- First, release stale locks
UPDATE ops.outbox
SET status = 'pending',
    locked_at = NULL,
    locked_by = NULL
WHERE status = 'processing'
    AND locked_at < now() - v_lock_timeout;
-- Claim pending messages
RETURN QUERY
UPDATE ops.outbox
SET status = 'processing',
    locked_at = now(),
    locked_by = p_worker_id,
    attempts = attempts + 1
WHERE id IN (
        SELECT id
        FROM ops.outbox
        WHERE channel = p_channel
            AND status = 'pending'
        ORDER BY created_at
        LIMIT p_batch_size FOR
        UPDATE SKIP LOCKED
    )
RETURNING *;
END;
$$;
COMMENT ON FUNCTION ops.claim_outbox_messages IS 'Claims a batch of pending outbox messages for processing. Releases stale locks first.';
-- Mark message as complete
CREATE OR REPLACE FUNCTION ops.complete_outbox_message(p_id uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,
    ops AS $$ BEGIN
UPDATE ops.outbox
SET status = 'complete',
    processed_at = now(),
    locked_at = NULL,
    locked_by = NULL
WHERE id = p_id;
END;
$$;
COMMENT ON FUNCTION ops.complete_outbox_message IS 'Marks an outbox message as successfully processed.';
-- Mark message as failed
CREATE OR REPLACE FUNCTION ops.fail_outbox_message(p_id uuid, p_error text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,
    ops AS $$
DECLARE v_attempts int;
v_max_attempts int;
BEGIN
SELECT attempts,
    max_attempts INTO v_attempts,
    v_max_attempts
FROM ops.outbox
WHERE id = p_id;
IF v_attempts >= v_max_attempts THEN -- Move to dead letter
UPDATE ops.outbox
SET status = 'dead_letter',
    last_error = p_error,
    processed_at = now(),
    locked_at = NULL,
    locked_by = NULL
WHERE id = p_id;
ELSE -- Return to pending for retry
UPDATE ops.outbox
SET status = 'pending',
    last_error = p_error,
    locked_at = NULL,
    locked_by = NULL
WHERE id = p_id;
END IF;
END;
$$;
COMMENT ON FUNCTION ops.fail_outbox_message IS 'Records a processing failure. Moves to dead_letter after max_attempts.';
-- Enqueue a new outbox message (called from business transactions)
CREATE OR REPLACE FUNCTION ops.enqueue_outbox(
        p_channel text,
        p_payload jsonb,
        p_correlation_id uuid DEFAULT NULL,
        p_max_attempts int DEFAULT 3
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,
    ops AS $$
DECLARE v_id uuid;
BEGIN
INSERT INTO ops.outbox (channel, payload, correlation_id, max_attempts)
VALUES (
        p_channel,
        p_payload,
        p_correlation_id,
        p_max_attempts
    )
RETURNING id INTO v_id;
RETURN v_id;
END;
$$;
COMMENT ON FUNCTION ops.enqueue_outbox IS 'Enqueues a new outbox message. Call from within business transactions for reliability.';
-- =============================================================================
-- Outbox Metrics View
-- =============================================================================
CREATE OR REPLACE VIEW ops.v_outbox_metrics AS
SELECT channel,
    COUNT(*) FILTER (
        WHERE status = 'pending'
    ) AS pending_count,
    COUNT(*) FILTER (
        WHERE status = 'processing'
    ) AS processing_count,
    COUNT(*) FILTER (
        WHERE status = 'complete'
    ) AS complete_24h,
    COUNT(*) FILTER (
        WHERE status = 'failed'
    ) AS failed_24h,
    COUNT(*) FILTER (
        WHERE status = 'dead_letter'
    ) AS dead_letter_count,
    AVG(
        EXTRACT(
            EPOCH
            FROM (processed_at - created_at)
        )
    ) FILTER (
        WHERE status = 'complete'
    ) AS avg_latency_seconds,
    MAX(created_at) FILTER (
        WHERE status = 'pending'
    ) AS oldest_pending_at
FROM ops.outbox
WHERE created_at >= now() - INTERVAL '24 hours'
    OR status IN ('pending', 'processing', 'dead_letter')
GROUP BY channel;
COMMENT ON VIEW ops.v_outbox_metrics IS 'Outbox processing metrics by channel';
-- =============================================================================
-- Security: RLS + Grants
-- =============================================================================
ALTER TABLE ops.outbox ENABLE ROW LEVEL SECURITY;
-- Service role has full access
DROP POLICY IF EXISTS "service_role_outbox" ON ops.outbox;
CREATE POLICY "service_role_outbox" ON ops.outbox FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Dragonfly app role can read/write
DROP POLICY IF EXISTS "dragonfly_app_outbox" ON ops.outbox;
CREATE POLICY "dragonfly_app_outbox" ON ops.outbox FOR ALL TO dragonfly_app USING (true) WITH CHECK (true);
-- Grants
GRANT SELECT,
    INSERT,
    UPDATE ON ops.outbox TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE ON ops.outbox TO dragonfly_app;
GRANT SELECT ON ops.v_outbox_metrics TO service_role,
    dragonfly_app;
GRANT EXECUTE ON FUNCTION ops.claim_outbox_messages TO service_role,
    dragonfly_app;
GRANT EXECUTE ON FUNCTION ops.complete_outbox_message TO service_role,
    dragonfly_app;
GRANT EXECUTE ON FUNCTION ops.fail_outbox_message TO service_role,
    dragonfly_app;
GRANT EXECUTE ON FUNCTION ops.enqueue_outbox TO service_role,
    dragonfly_app;
-- =============================================================================
-- Job Queue: Add dead_letter_at column if missing
-- =============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'job_queue'
        AND column_name = 'dead_letter_at'
) THEN
ALTER TABLE ops.job_queue
ADD COLUMN dead_letter_at timestamptz;
COMMENT ON COLUMN ops.job_queue.dead_letter_at IS 'Timestamp when job was moved to dead letter status';
END IF;
END $$;
