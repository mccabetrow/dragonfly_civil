-- Migration: Offer Engine for Transaction Tracking
-- Version: Dragonfly Engine v0.2.x
-- Description: Creates tables and views for tracking offers on judgments
-- ============================================================================
-- ============================================================================
-- 1. Ensure enforcement schema exists
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS enforcement;
-- ============================================================================
-- 2. Create enums safely (wrapped in DO blocks for idempotency)
-- ============================================================================
-- Offer type enum
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'offer_type'
        AND typnamespace = (
            SELECT oid
            FROM pg_namespace
            WHERE nspname = 'enforcement'
        )
) THEN CREATE TYPE enforcement.offer_type AS ENUM ('purchase', 'contingency');
END IF;
END $$;
-- Offer status enum
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'offer_status'
        AND typnamespace = (
            SELECT oid
            FROM pg_namespace
            WHERE nspname = 'enforcement'
        )
) THEN CREATE TYPE enforcement.offer_status AS ENUM ('offered', 'accepted', 'rejected', 'negotiation');
END IF;
END $$;
-- ============================================================================
-- 3. Create enforcement.offers table
-- ============================================================================
CREATE TABLE IF NOT EXISTS enforcement.offers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    judgment_id BIGINT NOT NULL REFERENCES public.judgments(id) ON DELETE CASCADE,
    offer_amount NUMERIC(12, 2) NOT NULL,
    offer_type enforcement.offer_type NOT NULL,
    status enforcement.offer_status NOT NULL DEFAULT 'offered',
    operator_notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE enforcement.offers IS 'Tracks offers made on judgments (purchase or contingency)';
COMMENT ON COLUMN enforcement.offers.judgment_id IS 'Reference to the judgment being offered on';
COMMENT ON COLUMN enforcement.offers.offer_amount IS 'Dollar amount of the offer';
COMMENT ON COLUMN enforcement.offers.offer_type IS 'Type of offer: purchase (buy outright) or contingency (collection fee)';
COMMENT ON COLUMN enforcement.offers.status IS 'Current status: offered, accepted, rejected, negotiation';
COMMENT ON COLUMN enforcement.offers.operator_notes IS 'Internal notes from the operator making the offer';
-- ============================================================================
-- 4. Create indexes for common queries
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_offers_judgment_id ON enforcement.offers(judgment_id);
CREATE INDEX IF NOT EXISTS idx_offers_created_at ON enforcement.offers(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_offers_status ON enforcement.offers(status);
-- ============================================================================
-- 5. Create offer statistics view
-- ============================================================================
CREATE OR REPLACE VIEW enforcement.v_offer_stats AS
SELECT judgment_id,
    COUNT(*) AS total_offers,
    COUNT(*) FILTER (
        WHERE status = 'offered'
    ) AS offers_made,
    COUNT(*) FILTER (
        WHERE status = 'accepted'
    ) AS offers_accepted,
    COUNT(*) FILTER (
        WHERE status = 'rejected'
    ) AS offers_rejected,
    COUNT(*) FILTER (
        WHERE status = 'negotiation'
    ) AS offers_in_negotiation,
    MAX(offer_amount) AS max_offer_amount,
    MIN(offer_amount) AS min_offer_amount,
    MAX(created_at) AS last_offer_at
FROM enforcement.offers
GROUP BY judgment_id;
COMMENT ON VIEW enforcement.v_offer_stats IS 'Aggregated offer statistics per judgment';
-- ============================================================================
-- 6. Create global offer metrics view (for dashboard)
-- ============================================================================
CREATE OR REPLACE VIEW enforcement.v_offer_metrics AS
SELECT COUNT(*) AS total_offers,
    COUNT(*) FILTER (
        WHERE status = 'accepted'
    ) AS accepted,
    COUNT(*) FILTER (
        WHERE status = 'rejected'
    ) AS rejected,
    COUNT(*) FILTER (
        WHERE status = 'negotiation'
    ) AS negotiation,
    COUNT(*) FILTER (
        WHERE status = 'offered'
    ) AS pending,
    CASE
        WHEN COUNT(*) > 0 THEN ROUND(
            (
                COUNT(*) FILTER (
                    WHERE status = 'accepted'
                )
            )::NUMERIC / COUNT(*) * 100,
            2
        )
        ELSE 0
    END AS conversion_rate_pct,
    SUM(offer_amount) FILTER (
        WHERE status = 'accepted'
    ) AS total_accepted_value,
    AVG(offer_amount) FILTER (
        WHERE status = 'accepted'
    ) AS avg_accepted_value
FROM enforcement.offers;
COMMENT ON VIEW enforcement.v_offer_metrics IS 'Global offer metrics for executive dashboard';
-- ============================================================================
-- 7. Grant permissions
-- ============================================================================
GRANT USAGE ON SCHEMA enforcement TO authenticated;
GRANT USAGE ON SCHEMA enforcement TO service_role;
GRANT ALL ON enforcement.offers TO service_role;
GRANT SELECT ON enforcement.offers TO authenticated;
GRANT SELECT ON enforcement.v_offer_stats TO authenticated;
GRANT SELECT ON enforcement.v_offer_stats TO service_role;
GRANT SELECT ON enforcement.v_offer_metrics TO authenticated;
GRANT SELECT ON enforcement.v_offer_metrics TO service_role;
