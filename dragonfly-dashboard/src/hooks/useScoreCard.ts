/**
 * useScoreCard
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Hook for fetching score breakdown data from enforcement.v_score_card.
 * Returns the total score and component breakdown (employment, assets, recency, banking).
 */
import { useCallback, useEffect, useState } from 'react';
import { IS_DEMO_MODE, supabaseClient } from '../lib/supabaseClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface ScoreCardData {
  id: number;
  caseNumber: string;
  plaintiffName: string | null;
  defendantName: string | null;
  judgmentAmount: number | null;
  totalScore: number | null;
  scoreEmployment: number;
  scoreAssets: number;
  scoreRecency: number;
  scoreBanking: number;
  breakdownSum: number;
  breakdownMatchesTotal: boolean;
}

export interface ScoreCardResult {
  data: ScoreCardData | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

/** Maximum points for each score component */
export const SCORE_LIMITS = {
  employment: 40,
  assets: 30,
  recency: 20,
  banking: 10,
} as const;

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useScoreCard(judgmentId: number | null): ScoreCardResult {
  const [data, setData] = useState<ScoreCardData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!judgmentId) {
      setData(null);
      setError(null);
      return;
    }

    if (IS_DEMO_MODE) {
      // Return mock data for demo mode
      setData({
        id: judgmentId,
        caseNumber: 'DEMO-2024-001',
        plaintiffName: 'Demo Plaintiff',
        defendantName: 'Demo Defendant',
        judgmentAmount: 50000,
        totalScore: 72,
        scoreEmployment: 32,
        scoreAssets: 22,
        scoreRecency: 12,
        scoreBanking: 6,
        breakdownSum: 72,
        breakdownMatchesTotal: true,
      });
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const { data: row, error: queryError } = await supabaseClient
        .from('v_score_card')
        .select('*')
        .eq('id', judgmentId)
        .single();

      if (queryError) {
        // Handle "not found" gracefully
        if (queryError.code === 'PGRST116') {
          setError('Score card not found for this judgment');
        } else {
          setError(queryError.message);
        }
        setData(null);
        return;
      }

      if (!row) {
        setError('No data returned');
        setData(null);
        return;
      }

      setData({
        id: row.id,
        caseNumber: row.case_number ?? '',
        plaintiffName: row.plaintiff_name,
        defendantName: row.defendant_name,
        judgmentAmount: row.judgment_amount,
        totalScore: row.total_score,
        scoreEmployment: row.score_employment ?? 0,
        scoreAssets: row.score_assets ?? 0,
        scoreRecency: row.score_recency ?? 0,
        scoreBanking: row.score_banking ?? 0,
        breakdownSum: row.breakdown_sum ?? 0,
        breakdownMatchesTotal: row.breakdown_matches_total ?? false,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error fetching score card');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [judgmentId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return {
    data,
    loading,
    error,
    refetch: fetchData,
  };
}
