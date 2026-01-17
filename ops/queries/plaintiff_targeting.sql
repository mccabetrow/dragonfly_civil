-- =============================================================================
-- Operator SQL Queries for Plaintiff Targeting / Perfect Plaintiffs Engine
-- =============================================================================
--
-- This file contains production operator queries for monitoring and
-- troubleshooting the plaintiff targeting pipeline.
--
-- The Perfect Plaintiffs Engine transforms raw judgments into scored,
-- prioritized leads for outreach.
--
-- =============================================================================
-- =============================================================================
-- 1. TIER DISTRIBUTION - Lead counts by priority tier
-- =============================================================================
-- Quick health check: shows distribution of leads across priority tiers
SELECT priority_tier,
    COUNT(*) AS lead_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_total,
    ROUND(AVG(collectability_score), 1) AS avg_score,
    ROUND(AVG(judgment_amount)::numeric, 0) AS avg_judgment,
    ROUND(SUM(judgment_amount)::numeric, 0) AS total_judgment_value
FROM public.plaintiff_leads
GROUP BY priority_tier
ORDER BY CASE
        priority_tier
        WHEN 'A' THEN 1
        WHEN 'B' THEN 2
        WHEN 'C' THEN 3
        WHEN 'D' THEN 4
        ELSE 5
    END;
-- =============================================================================
-- 2. TOP LEADS QUEUE - Platinum (A) and Gold (B) leads ready for outreach
-- =============================================================================
-- Priority-ordered list of actionable leads for sales team
SELECT id,
    priority_tier,
    collectability_score,
    plaintiff_name,
    debtor_name,
    debtor_type,
    ROUND(judgment_amount::numeric, 2) AS judgment_amount,
    judgment_entered_at,
    days_since_judgment,
    plaintiff_phone,
    plaintiff_email,
    attorney_name,
    source_county,
    case_number,
    scored_at
FROM public.plaintiff_leads
WHERE outreach_status = 'pending'
    AND priority_tier IN ('A', 'B')
ORDER BY CASE
        priority_tier
        WHEN 'A' THEN 1
        WHEN 'B' THEN 2
    END,
    collectability_score DESC,
    judgment_amount DESC
LIMIT 100;
-- =============================================================================
-- 3. TARGETING RUNS - Recent worker executions
-- =============================================================================
-- Audit trail of worker runs with performance metrics
SELECT id,
    started_at,
    finished_at,
    status,
    judgments_evaluated,
    leads_created,
    leads_updated,
    leads_skipped,
    ROUND(duration_ms / 1000.0, 1) AS duration_sec,
    source_county,
    source_system,
    min_score_threshold,
    error_message
FROM public.targeting_runs
ORDER BY started_at DESC
LIMIT 20;
-- =============================================================================
-- 4. DAILY LEAD GENERATION - Leads created per day
-- =============================================================================
-- Trend analysis for lead generation velocity
SELECT DATE(scored_at) AS score_date,
    COUNT(*) AS leads_scored,
    COUNT(*) FILTER (
        WHERE priority_tier = 'A'
    ) AS tier_a,
    COUNT(*) FILTER (
        WHERE priority_tier = 'B'
    ) AS tier_b,
    COUNT(*) FILTER (
        WHERE priority_tier = 'C'
    ) AS tier_c,
    COUNT(*) FILTER (
        WHERE priority_tier = 'D'
    ) AS tier_d,
    COUNT(*) FILTER (
        WHERE priority_tier = 'F'
    ) AS tier_f,
    ROUND(AVG(collectability_score), 1) AS avg_score,
    ROUND(SUM(judgment_amount)::numeric, 0) AS total_value
FROM public.plaintiff_leads
WHERE scored_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY DATE(scored_at)
ORDER BY score_date DESC;
-- =============================================================================
-- 5. COUNTY DISTRIBUTION - Leads by source county
-- =============================================================================
-- Geographic analysis for regional targeting
SELECT COALESCE(source_county, 'unknown') AS county,
    COUNT(*) AS lead_count,
    COUNT(*) FILTER (
        WHERE priority_tier IN ('A', 'B')
    ) AS high_priority,
    ROUND(AVG(collectability_score), 1) AS avg_score,
    ROUND(SUM(judgment_amount)::numeric, 0) AS total_value,
    ROUND(AVG(days_since_judgment), 0) AS avg_days_old
FROM public.plaintiff_leads
GROUP BY COALESCE(source_county, 'unknown')
ORDER BY lead_count DESC;
-- =============================================================================
-- 6. DEBTOR TYPE ANALYSIS - Leads by debtor classification
-- =============================================================================
-- Business vs individual performance comparison
SELECT debtor_type,
    COUNT(*) AS lead_count,
    ROUND(AVG(collectability_score), 1) AS avg_score,
    ROUND(AVG(judgment_amount)::numeric, 0) AS avg_judgment,
    COUNT(*) FILTER (
        WHERE priority_tier IN ('A', 'B')
    ) AS high_priority,
    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE priority_tier IN ('A', 'B')
        ) / COUNT(*),
        1
    ) AS pct_high_priority
FROM public.plaintiff_leads
GROUP BY debtor_type
ORDER BY avg_score DESC;
-- =============================================================================
-- 7. OUTREACH FUNNEL - Leads by outreach status
-- =============================================================================
-- Conversion funnel from lead to engagement
SELECT outreach_status,
    COUNT(*) AS lead_count,
    ROUND(AVG(collectability_score), 1) AS avg_score,
    ROUND(SUM(judgment_amount)::numeric, 0) AS total_value,
    ROUND(AVG(outreach_attempts), 1) AS avg_attempts,
    MAX(last_outreach_at) AS last_outreach
FROM public.plaintiff_leads
GROUP BY outreach_status
ORDER BY CASE
        outreach_status
        WHEN 'pending' THEN 1
        WHEN 'contacted' THEN 2
        WHEN 'responded' THEN 3
        WHEN 'converted' THEN 4
        WHEN 'rejected' THEN 5
        WHEN 'archived' THEN 6
    END;
-- =============================================================================
-- 8. STALE PENDING LEADS - High-priority leads untouched for too long
-- =============================================================================
-- Action items: leads that should have been contacted
SELECT id,
    priority_tier,
    collectability_score,
    plaintiff_name,
    debtor_name,
    ROUND(judgment_amount::numeric, 2) AS judgment_amount,
    days_since_judgment,
    scored_at,
    EXTRACT(
        DAYS
        FROM (NOW() - scored_at)
    ) AS days_since_scored
FROM public.plaintiff_leads
WHERE outreach_status = 'pending'
    AND priority_tier IN ('A', 'B')
    AND scored_at < NOW() - INTERVAL '7 days'
ORDER BY collectability_score DESC,
    judgment_amount DESC
LIMIT 50;
-- =============================================================================
-- 9. SCORE COMPONENT BREAKDOWN - Analysis of scoring factors
-- =============================================================================
-- Identify which factors drive scores in the current dataset
SELECT priority_tier,
    ROUND(AVG(score_amount), 1) AS avg_amount_pts,
    ROUND(AVG(score_recency), 1) AS avg_recency_pts,
    ROUND(AVG(score_debtor_type), 1) AS avg_debtor_pts,
    ROUND(AVG(score_address), 1) AS avg_address_pts,
    ROUND(AVG(score_contact), 1) AS avg_contact_pts,
    ROUND(AVG(score_asset_signals), 1) AS avg_asset_pts,
    COUNT(*) AS lead_count
FROM public.plaintiff_leads
GROUP BY priority_tier
ORDER BY CASE
        priority_tier
        WHEN 'A' THEN 1
        WHEN 'B' THEN 2
        WHEN 'C' THEN 3
        WHEN 'D' THEN 4
        ELSE 5
    END;
-- =============================================================================
-- 10. IDEMPOTENCY CHECK - Verify no duplicate leads
-- =============================================================================
-- Data quality check: should return 0 rows if idempotency is working
SELECT dedupe_key,
    COUNT(*) AS duplicates
FROM public.plaintiff_leads
GROUP BY dedupe_key
HAVING COUNT(*) > 1;
-- =============================================================================
-- 11. UNPROCESSED JUDGMENTS - Raw judgments not yet targeted
-- =============================================================================
-- Backlog of judgments awaiting scoring
SELECT jr.source_system,
    jr.source_county,
    COUNT(*) AS pending_count,
    MIN(jr.judgment_entered_at) AS oldest_judgment,
    MAX(jr.captured_at) AS latest_captured
FROM public.judgments_raw jr
    LEFT JOIN public.plaintiff_leads pl ON pl.source_judgment_id = jr.id
WHERE pl.id IS NULL
    AND jr.status IN ('pending', 'processed')
GROUP BY jr.source_system,
    jr.source_county
ORDER BY pending_count DESC;
-- =============================================================================
-- 12. WORKER PERFORMANCE - Targeting run statistics
-- =============================================================================
-- Aggregated performance metrics across worker runs
SELECT DATE(started_at) AS run_date,
    COUNT(*) AS runs,
    SUM(judgments_evaluated) AS total_evaluated,
    SUM(leads_created) AS total_created,
    SUM(leads_updated) AS total_updated,
    SUM(leads_skipped) AS total_skipped,
    ROUND(AVG(duration_ms / 1000.0), 1) AS avg_duration_sec,
    COUNT(*) FILTER (
        WHERE status = 'completed'
    ) AS successful,
    COUNT(*) FILTER (
        WHERE status = 'failed'
    ) AS failed
FROM public.targeting_runs
WHERE started_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY DATE(started_at)
ORDER BY run_date DESC;
-- =============================================================================
-- 13. HIGH-VALUE LEADS - Top judgment amounts
-- =============================================================================
-- Focus list for highest-value opportunities
SELECT id,
    priority_tier,
    collectability_score,
    plaintiff_name,
    debtor_name,
    ROUND(judgment_amount::numeric, 2) AS judgment_amount,
    judgment_entered_at,
    days_since_judgment,
    plaintiff_phone,
    attorney_name,
    source_county,
    outreach_status
FROM public.plaintiff_leads
WHERE judgment_amount >= 25000
    AND outreach_status = 'pending'
ORDER BY judgment_amount DESC,
    collectability_score DESC
LIMIT 50;
-- =============================================================================
-- 14. FRESH LEADS - Recently scored, ready for outreach
-- =============================================================================
-- New leads from the last 7 days
SELECT id,
    priority_tier,
    collectability_score,
    plaintiff_name,
    debtor_name,
    ROUND(judgment_amount::numeric, 2) AS judgment_amount,
    days_since_judgment,
    plaintiff_phone,
    scored_at
FROM public.plaintiff_leads
WHERE scored_at >= CURRENT_DATE - INTERVAL '7 days'
    AND outreach_status = 'pending'
    AND priority_tier IN ('A', 'B', 'C')
ORDER BY priority_tier,
    collectability_score DESC
LIMIT 100;
-- =============================================================================
-- 15. DASHBOARD SUMMARY - Single-row overview
-- =============================================================================
-- Quick snapshot for executive dashboards
SELECT COUNT(*) AS total_leads,
    COUNT(*) FILTER (
        WHERE priority_tier = 'A'
    ) AS tier_a_leads,
    COUNT(*) FILTER (
        WHERE priority_tier = 'B'
    ) AS tier_b_leads,
    COUNT(*) FILTER (
        WHERE priority_tier IN ('A', 'B')
            AND outreach_status = 'pending'
    ) AS actionable_leads,
    ROUND(AVG(collectability_score), 1) AS avg_score,
    ROUND(SUM(judgment_amount)::numeric, 0) AS total_judgment_value,
    ROUND(
        SUM(judgment_amount) FILTER (
            WHERE priority_tier IN ('A', 'B')
        )::numeric,
        0
    ) AS high_priority_value,
    COUNT(*) FILTER (
        WHERE scored_at >= CURRENT_DATE - INTERVAL '24 hours'
    ) AS leads_last_24h,
    (
        SELECT COUNT(*)
        FROM public.targeting_runs
        WHERE status = 'completed'
            AND started_at >= CURRENT_DATE - INTERVAL '24 hours'
    ) AS runs_last_24h
FROM public.plaintiff_leads;