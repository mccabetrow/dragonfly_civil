-- 0211_tier_assignment.sql
-- Add tier columns to core_judgments and enable tier_assignment queue kind.
--
-- This migration supports the nightly tier assignment worker which evaluates
-- each judgment's collectability_score, balance, and debtor_intelligence to
-- assign an enforcement tier (0-3) per docs/enforcement_tiers.md.
--
-- Tier Policy:
--   0 = Monitor: low collectability or small balance with no assets
--   1 = Warm Prospects: moderate collectability, mid-range balance
--   2 = Active Enforcement: good collectability or larger balance with assets
--   3 = Strategic/Priority: high collectability or large balance with multiple assets
-- ============================================================================
-- 1. Add tier columns to core_judgments
-- ============================================================================
ALTER TABLE public.core_judgments
ADD COLUMN IF NOT EXISTS tier smallint DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS tier_reason text DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS tier_as_of timestamptz DEFAULT NULL;
-- Add check constraint for valid tier values
ALTER TABLE public.core_judgments DROP CONSTRAINT IF EXISTS core_judgments_tier_check;
ALTER TABLE public.core_judgments
ADD CONSTRAINT core_judgments_tier_check CHECK (
        tier IS NULL
        OR (
            tier >= 0
            AND tier <= 3
        )
    );
-- Index for tier-based queries and dashboard views
CREATE INDEX IF NOT EXISTS idx_core_judgments_tier ON public.core_judgments(tier)
WHERE tier IS NOT NULL;
COMMENT ON COLUMN public.core_judgments.tier IS 'Enforcement tier (0-3). 0=Monitor, 1=Warm, 2=Active, 3=Strategic';
COMMENT ON COLUMN public.core_judgments.tier_reason IS 'Human-readable explanation of tier assignment';
COMMENT ON COLUMN public.core_judgments.tier_as_of IS 'Timestamp when tier was last computed';
-- ============================================================================
-- 2. Create PGMQ queue for tier_assignment
-- ============================================================================
DO $$ BEGIN IF to_regclass('pgmq.q_tier_assignment') IS NULL THEN BEGIN PERFORM pgmq.create('tier_assignment');
EXCEPTION
WHEN undefined_function THEN BEGIN PERFORM pgmq.create_queue('tier_assignment');
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'pgmq.create and pgmq.create_queue unavailable; queue tier_assignment not created';
WHEN OTHERS THEN IF SQLSTATE IN ('42710', '42P07') THEN NULL;
-- Queue already exists
ELSE RAISE;
END IF;
END;
WHEN OTHERS THEN IF SQLSTATE IN ('42710', '42P07') THEN NULL;
-- Queue already exists
ELSE RAISE;
END IF;
END;
END IF;
END;
$$;
-- ============================================================================
-- 3. Update queue_job to accept 'tier_assignment' kind
-- ============================================================================
CREATE OR REPLACE FUNCTION public.queue_job(payload jsonb) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_kind text;
v_idempotency_key text;
v_body jsonb;
BEGIN v_kind := payload->>'kind';
v_idempotency_key := payload->>'idempotency_key';
v_body := coalesce(payload->'payload', '{}'::jsonb);
IF v_kind IS NULL THEN RAISE EXCEPTION 'queue_job: missing kind in payload';
END IF;
IF v_kind NOT IN (
    'enrich',
    'outreach',
    'enforce',
    'case_copilot',
    'collectability',
    'judgment_enrich',
    'enforcement_action',
    'tier_assignment'
) THEN RAISE EXCEPTION 'queue_job: unsupported kind %',
v_kind;
END IF;
IF v_idempotency_key IS NULL
OR length(v_idempotency_key) = 0 THEN RAISE EXCEPTION 'queue_job: missing idempotency_key';
END IF;
RETURN pgmq.send(
    v_kind,
    jsonb_build_object(
        'payload',
        v_body,
        'idempotency_key',
        v_idempotency_key,
        'kind',
        v_kind,
        'enqueued_at',
        now()
    )
);
END;
$$;
-- ============================================================================
-- 4. Update dequeue_job to accept 'tier_assignment' kind
-- ============================================================================
CREATE OR REPLACE FUNCTION public.dequeue_job(kind text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE msg record;
BEGIN IF kind IS NULL
OR length(trim(kind)) = 0 THEN RAISE EXCEPTION 'dequeue_job: missing kind';
END IF;
IF kind NOT IN (
    'enrich',
    'outreach',
    'enforce',
    'case_copilot',
    'collectability',
    'judgment_enrich',
    'enforcement_action',
    'tier_assignment'
) THEN RAISE EXCEPTION 'dequeue_job: unsupported kind %',
kind;
END IF;
SELECT * INTO msg
FROM pgmq.read(kind, 1, 30);
IF msg IS NULL THEN RETURN NULL;
END IF;
RETURN jsonb_build_object(
    'msg_id',
    msg.msg_id,
    'vt',
    msg.vt,
    'read_ct',
    msg.read_ct,
    'enqueued_at',
    msg.enqueued_at,
    'payload',
    msg.message,
    'body',
    msg.message
);
END;
$$;
-- ============================================================================
-- 5. Grants and documentation
-- ============================================================================
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO anon;
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO authenticated;
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.dequeue_job(text) TO service_role;
COMMENT ON FUNCTION public.queue_job IS 'Enqueue a job to PGMQ. Supported kinds: enrich, outreach, enforce, case_copilot, collectability, judgment_enrich, enforcement_action, tier_assignment.';
COMMENT ON FUNCTION public.dequeue_job IS 'Dequeue a job from PGMQ. Supported kinds: enrich, outreach, enforce, case_copilot, collectability, judgment_enrich, enforcement_action, tier_assignment.';
-- ============================================================================
-- 6. Dashboard view: v_enforcement_tier_overview
-- ============================================================================
CREATE OR REPLACE VIEW public.v_enforcement_tier_overview AS
SELECT tier,
    CASE
        tier
        WHEN 0 THEN 'Monitor'
        WHEN 1 THEN 'Warm Prospects'
        WHEN 2 THEN 'Active Enforcement'
        WHEN 3 THEN 'Strategic/Priority'
        ELSE 'Unassigned'
    END AS tier_label,
    count(*) AS judgment_count,
    sum(principal_amount) AS total_principal,
    avg(principal_amount) AS avg_principal,
    avg(collectability_score) AS avg_collectability,
    sum(
        CASE
            WHEN status NOT IN ('satisfied', 'vacated', 'expired') THEN 1
            ELSE 0
        END
    ) AS active_count,
    min(tier_as_of) AS oldest_tier_assignment,
    max(tier_as_of) AS newest_tier_assignment
FROM public.core_judgments
GROUP BY tier
ORDER BY tier NULLS LAST;
COMMENT ON VIEW public.v_enforcement_tier_overview IS 'Summary of judgments by enforcement tier for dashboard consumption';
GRANT SELECT ON public.v_enforcement_tier_overview TO anon;
GRANT SELECT ON public.v_enforcement_tier_overview TO authenticated;
GRANT SELECT ON public.v_enforcement_tier_overview TO service_role;
