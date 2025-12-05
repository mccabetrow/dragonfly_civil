/**
 * useCeoOverviewStats
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Aggregates portfolio-level statistics for the CEO Overview page.
 * Queries enforcement.v_radar, enforcement.v_offer_stats, and ops.v_enrichment_health.
 */
import { useCallback, useEffect, useState } from 'react';
import { IS_DEMO_MODE, supabaseClient } from '../lib/supabaseClient';
import { useOnRefresh } from '../context/RefreshContext';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface CeoOverviewStats {
  // Portfolio Overview
  totalJudgments: number;
  totalJudgmentValue: number;

  // Buy Candidates
  buyCandidateCount: number;
  buyCandidateValue: number;

  // Contingency
  contingencyCount: number;
  contingencyValue: number;

  // Offers
  totalOffers: number;
  offersAccepted: number;
  offersRejected: number;
  offersPending: number;
  acceptanceRate: number;
  totalOfferedAmount: number;
  totalAcceptedAmount: number;

  // System Health
  systemHealthy: boolean;
  pendingJobs: number;
  failedJobs: number;
  lastActivityAt: string | null;
}

export interface CeoOverviewResult {
  data: CeoOverviewStats | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// DEMO DATA
// ═══════════════════════════════════════════════════════════════════════════

const DEMO_STATS: CeoOverviewStats = {
  totalJudgments: 1247,
  totalJudgmentValue: 42850000,
  buyCandidateCount: 156,
  buyCandidateValue: 8920000,
  contingencyCount: 412,
  contingencyValue: 15600000,
  totalOffers: 127,
  offersAccepted: 42,
  offersRejected: 31,
  offersPending: 54,
  acceptanceRate: 57.5,
  totalOfferedAmount: 3200000,
  totalAcceptedAmount: 1850000,
  systemHealthy: true,
  pendingJobs: 3,
  failedJobs: 0,
  lastActivityAt: new Date().toISOString(),
};

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useCeoOverviewStats(): CeoOverviewResult {
  const [data, setData] = useState<CeoOverviewStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setData(DEMO_STATS);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Fetch radar stats (portfolio overview)
      const radarPromise = supabaseClient
        .from('v_radar')
        .select('id, offer_strategy, judgment_amount');

      // Fetch offer stats
      const offersPromise = supabaseClient
        .from('v_offer_stats')
        .select('status, offered_amount, accepted_amount');

      // Fetch system health
      const healthPromise = supabaseClient
        .from('v_enrichment_health')
        .select('pending_jobs, failed_jobs, last_job_updated_at')
        .limit(1)
        .single();

      const [radarResult, offersResult, healthResult] = await Promise.all([
        radarPromise,
        offersPromise,
        healthPromise,
      ]);

      // Process radar data
      const radarRows = radarResult.data ?? [];
      const totalJudgments = radarRows.length;
      const totalJudgmentValue = radarRows.reduce(
        (sum, row) => sum + (Number(row.judgment_amount) || 0),
        0
      );

      const buyRows = radarRows.filter((r) => r.offer_strategy === 'BUY_CANDIDATE');
      const buyCandidateCount = buyRows.length;
      const buyCandidateValue = buyRows.reduce(
        (sum, row) => sum + (Number(row.judgment_amount) || 0),
        0
      );

      const contingencyRows = radarRows.filter((r) => r.offer_strategy === 'CONTINGENCY');
      const contingencyCount = contingencyRows.length;
      const contingencyValue = contingencyRows.reduce(
        (sum, row) => sum + (Number(row.judgment_amount) || 0),
        0
      );

      // Process offers data
      const offerRows = offersResult.data ?? [];
      const totalOffers = offerRows.length;
      const offersAccepted = offerRows.filter((r) => r.status === 'accepted').length;
      const offersRejected = offerRows.filter((r) => r.status === 'rejected').length;
      const offersPending = offerRows.filter(
        (r) => r.status === 'pending' || r.status === 'negotiation'
      ).length;
      const resolved = offersAccepted + offersRejected;
      const acceptanceRate = resolved > 0 ? (offersAccepted / resolved) * 100 : 0;

      const totalOfferedAmount = offerRows.reduce(
        (sum, row) => sum + (Number(row.offered_amount) || 0),
        0
      );
      const totalAcceptedAmount = offerRows
        .filter((r) => r.status === 'accepted')
        .reduce((sum, row) => sum + (Number(row.accepted_amount) || 0), 0);

      // Process health data
      const healthRow = healthResult.data;
      const pendingJobs = Number(healthRow?.pending_jobs) || 0;
      const failedJobs = Number(healthRow?.failed_jobs) || 0;
      const systemHealthy = failedJobs === 0 && pendingJobs < 100;
      const lastActivityAt = healthRow?.last_job_updated_at ?? null;

      setData({
        totalJudgments,
        totalJudgmentValue,
        buyCandidateCount,
        buyCandidateValue,
        contingencyCount,
        contingencyValue,
        totalOffers,
        offersAccepted,
        offersRejected,
        offersPending,
        acceptanceRate,
        totalOfferedAmount,
        totalAcceptedAmount,
        systemHealthy,
        pendingJobs,
        failedJobs,
        lastActivityAt,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load CEO overview stats';
      console.error('useCeoOverviewStats error:', err);
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Subscribe to global refresh
  useOnRefresh(fetchData);

  return { data, loading, error, refetch: fetchData };
}

export default useCeoOverviewStats;
