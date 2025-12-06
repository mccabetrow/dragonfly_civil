/**
 * usePortfolioStats
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Aggregates portfolio-level AUM and financial metrics for the CEO Portfolio page.
 * Fetches from /api/v1/portfolio/stats via apiClient.
 *
 * Metrics:
 *   - Total AUM: sum of all judgment_amount
 *   - Actionable Liquidity: sum where collectability_score > 40
 *   - Pipeline Value: sum of judgment amounts tagged BUY_CANDIDATE
 *   - Offers Outstanding: count of pending offers
 *   - Score Tier Allocation: breakdown by A/B/C tiers
 *   - Top Counties: top 5 by judgment amount
 */
import { useCallback, useEffect, useState } from 'react';
import { apiClient, AuthError, NotFoundError } from '../lib/apiClient';
import { IS_DEMO_MODE } from '../lib/supabaseClient';
import { useOnRefresh } from '../context/RefreshContext';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface ScoreTierAllocation {
  tier: 'A' | 'B' | 'C';
  label: string;
  amount: number;
  count: number;
  color: string;
}

export interface CountyBreakdown {
  county: string;
  amount: number;
  count: number;
}

export interface PortfolioStats {
  /** Sum of all judgment_amount in the portfolio */
  totalAum: number;
  /** Sum where collectability_score > 40 */
  actionableLiquidity: number;
  /** Sum of amounts tagged as BUY_CANDIDATE */
  pipelineValue: number;
  /** Count of pending offers */
  offersOutstanding: number;
  /** Breakdown by score tier (A/B/C) */
  tierAllocation: ScoreTierAllocation[];
  /** Top 5 counties by total judgment amount */
  topCounties: CountyBreakdown[];
  /** Total judgment count */
  totalJudgments: number;
  /** Actionable judgment count (score > 40) */
  actionableCount: number;
}

export interface PortfolioStatsResult {
  data: PortfolioStats | null;
  loading: boolean;
  error: string | null;
  isAuthError: boolean;
  isNotFound: boolean;
  isError: boolean;
  refetch: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// DEMO DATA
// ═══════════════════════════════════════════════════════════════════════════

const DEMO_STATS: PortfolioStats = {
  totalAum: 48_750_000,
  actionableLiquidity: 22_340_000,
  pipelineValue: 8_920_000,
  offersOutstanding: 54,
  totalJudgments: 1247,
  actionableCount: 523,
  tierAllocation: [
    { tier: 'A', label: 'Tier A (80+)', amount: 12_500_000, count: 187, color: '#10b981' },
    { tier: 'B', label: 'Tier B (50-79)', amount: 18_750_000, count: 412, color: '#3b82f6' },
    { tier: 'C', label: 'Tier C (<50)', amount: 17_500_000, count: 648, color: '#6b7280' },
  ],
  topCounties: [
    { county: 'Nassau County', amount: 8_200_000, count: 156 },
    { county: 'Suffolk County', amount: 6_850_000, count: 134 },
    { county: 'Westchester County', amount: 5_420_000, count: 98 },
    { county: 'Kings County', amount: 4_980_000, count: 112 },
    { county: 'Queens County', amount: 4_150_000, count: 89 },
  ],
};

// ═══════════════════════════════════════════════════════════════════════════
// API RESPONSE TYPE
// ═══════════════════════════════════════════════════════════════════════════

interface ApiPortfolioStats {
  total_aum: number;
  actionable_liquidity: number;
  pipeline_value: number;
  offers_outstanding: number;
  total_judgments: number;
  actionable_count: number;
  tier_allocation: Array<{
    tier: 'A' | 'B' | 'C';
    label: string;
    amount: number;
    count: number;
    color: string;
  }>;
  top_counties: Array<{
    county: string;
    amount: number;
    count: number;
  }>;
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function usePortfolioStats(): PortfolioStatsResult {
  const [data, setData] = useState<PortfolioStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthError, setIsAuthError] = useState(false);
  const [isNotFound, setIsNotFound] = useState(false);
  const [isError, setIsError] = useState(false);

  const fetchData = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setData(DEMO_STATS);
      setLoading(false);
      setError(null);
      setIsAuthError(false);
      setIsNotFound(false);
      setIsError(false);
      return;
    }

    setLoading(true);
    setError(null);
    setIsAuthError(false);
    setIsNotFound(false);
    setIsError(false);

    try {
      const response = await apiClient.get<ApiPortfolioStats>('/api/v1/portfolio/stats');

      // Map snake_case API response to camelCase
      const stats: PortfolioStats = {
        totalAum: response.total_aum ?? 0,
        actionableLiquidity: response.actionable_liquidity ?? 0,
        pipelineValue: response.pipeline_value ?? 0,
        offersOutstanding: response.offers_outstanding ?? 0,
        totalJudgments: response.total_judgments ?? 0,
        actionableCount: response.actionable_count ?? 0,
        tierAllocation: (response.tier_allocation ?? []).map((t) => ({
          tier: t.tier,
          label: t.label,
          amount: t.amount,
          count: t.count,
          color: t.color,
        })),
        topCounties: (response.top_counties ?? []).map((c) => ({
          county: c.county,
          amount: c.amount,
          count: c.count,
        })),
      };

      setData(stats);
    } catch (err) {
      console.error('[usePortfolioStats]', err);

      if (err instanceof AuthError) {
        setError('Invalid API key – check Vercel VITE_DRAGONFLY_API_KEY vs Railway DRAGONFLY_API_KEY.');
        setIsAuthError(true);
      } else if (err instanceof NotFoundError) {
        setError('Metrics/view not configured yet.');
        setIsNotFound(true);
      } else {
        const message = err instanceof Error ? err.message : 'Failed to load portfolio stats';
        setError(message);
        setIsError(true);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Subscribe to global refresh
  useOnRefresh(fetchData);

  return { data, loading, error, isAuthError, isNotFound, isError, refetch: fetchData };
}

export default usePortfolioStats;
