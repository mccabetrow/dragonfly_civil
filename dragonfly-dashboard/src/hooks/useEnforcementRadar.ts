/**
 * useEnforcementRadar
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Fetches prioritized buy/contingency candidates via apiClient.
 * Returns RadarRow[] with collectability scores.
 */
import { useCallback, useEffect, useState } from 'react';
import { apiClient, AuthError, NotFoundError } from '../lib/apiClient';
import { IS_DEMO_MODE } from '../lib/supabaseClient';
import {
  buildDemoLockedState,
  buildErrorMetricsState,
  buildInitialMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  type MetricsHookResult,
  type MetricsState,
} from './metricsState';
import { useOnRefresh } from '../context/RefreshContext';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type OfferStrategy = 'BUY_CANDIDATE' | 'CONTINGENCY' | 'ENRICHMENT_PENDING' | 'LOW_PRIORITY';

export interface RadarRow {
  id: string;
  caseNumber: string;
  plaintiffName: string;
  defendantName: string;
  judgmentAmount: number;
  collectabilityScore: number | null;
  offerStrategy: OfferStrategy;
  court: string | null;
  county: string | null;
  judgmentDate: string | null;
  createdAt: string;
  hasEmployer: boolean;
  hasBank: boolean;
}

export interface RadarFilters {
  strategy?: OfferStrategy | 'ALL';
  minScore?: number;
  minAmount?: number;
  onlyEmployed?: boolean;
  onlyBankAssets?: boolean;
}

interface ApiRadarRow {
  id: string;
  case_number: string;
  plaintiff_name: string;
  defendant_name: string;
  judgment_amount: number;
  collectability_score: number | null;
  offer_strategy: string;
  court: string | null;
  county: string | null;
  judgment_date: string | null;
  created_at: string;
  has_employer: boolean;
  has_bank: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useEnforcementRadar(
  filters?: RadarFilters
): MetricsHookResult<RadarRow[]> {
  const [snapshot, setSnapshot] = useState<MetricsState<RadarRow[]>>(() =>
    buildInitialMetricsState<RadarRow[]>()
  );

  const fetchData = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<RadarRow[]>());
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      // Build query params for filtering
      const params = new URLSearchParams();
      if (filters?.strategy && filters.strategy !== 'ALL') {
        params.set('strategy', filters.strategy);
      }
      if (filters?.minScore !== undefined && filters.minScore > 0) {
        params.set('min_score', String(filters.minScore));
      }
      if (filters?.minAmount !== undefined && filters.minAmount > 0) {
        params.set('min_amount', String(filters.minAmount));
      }
      if (filters?.onlyEmployed) {
        params.set('only_employed', 'true');
      }
      if (filters?.onlyBankAssets) {
        params.set('only_bank_assets', 'true');
      }

      const queryString = params.toString();
      const path = `/api/v1/enforcement/radar${queryString ? `?${queryString}` : ''}`;

      const rows = await apiClient.get<ApiRadarRow[]>(path);

      const normalized: RadarRow[] = (rows ?? []).map((row) => ({
        id: String(row.id ?? ''),
        caseNumber: String(row.case_number ?? ''),
        plaintiffName: String(row.plaintiff_name ?? ''),
        defendantName: String(row.defendant_name ?? ''),
        judgmentAmount: Number(row.judgment_amount ?? 0),
        collectabilityScore: row.collectability_score != null ? Number(row.collectability_score) : null,
        offerStrategy: (row.offer_strategy as OfferStrategy) ?? 'ENRICHMENT_PENDING',
        court: row.court != null ? String(row.court) : null,
        county: row.county != null ? String(row.county) : null,
        judgmentDate: row.judgment_date != null ? String(row.judgment_date) : null,
        createdAt: String(row.created_at ?? ''),
        hasEmployer: Boolean(row.has_employer),
        hasBank: Boolean(row.has_bank),
      }));

      setSnapshot(buildReadyMetricsState(normalized));
    } catch (err) {
      console.error('[useEnforcementRadar]', err);

      if (err instanceof AuthError) {
        setSnapshot(
          buildErrorMetricsState<RadarRow[]>(err, {
            message: 'Invalid API key – check Vercel VITE_DRAGONFLY_API_KEY vs Railway DRAGONFLY_API_KEY.',
            isAuthError: true,
          })
        );
      } else if (err instanceof NotFoundError) {
        setSnapshot(
          buildErrorMetricsState<RadarRow[]>(err, {
            message: 'Metrics/view not configured yet.',
            isNotFound: true,
          })
        );
      } else {
        const error = err instanceof Error ? err : new Error('Unable to load enforcement radar.');
        setSnapshot(
          buildErrorMetricsState<RadarRow[]>(error, {
            message: 'Unable to load enforcement radar. Please try again.',
          })
        );
      }
    }
  }, [filters?.strategy, filters?.minScore, filters?.minAmount, filters?.onlyEmployed, filters?.onlyBankAssets]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  // Subscribe to global refresh
  useOnRefresh(() => fetchData());

  const refetch = useCallback(() => fetchData(), [fetchData]);

  return { ...snapshot, state: snapshot, refetch };
}

// ═══════════════════════════════════════════════════════════════════════════
// DERIVED METRICS
// ═══════════════════════════════════════════════════════════════════════════

export function computeRadarKPIs(rows: RadarRow[]) {
  const buyCandidates = rows.filter((r) => r.offerStrategy === 'BUY_CANDIDATE');
  const contingency = rows.filter((r) => r.offerStrategy === 'CONTINGENCY');
  const pending = rows.filter((r) => r.offerStrategy === 'ENRICHMENT_PENDING');
  const lowPriority = rows.filter((r) => r.offerStrategy === 'LOW_PRIORITY');

  const totalActionableValue = [...buyCandidates, ...contingency].reduce(
    (sum, r) => sum + r.judgmentAmount,
    0
  );

  const avgScore =
    rows.filter((r) => r.collectabilityScore != null).length > 0
      ? rows
          .filter((r) => r.collectabilityScore != null)
          .reduce((sum, r) => sum + (r.collectabilityScore ?? 0), 0) /
        rows.filter((r) => r.collectabilityScore != null).length
      : null;

  return {
    totalCases: rows.length,
    buyCandidateCount: buyCandidates.length,
    buyCandidateValue: buyCandidates.reduce((sum, r) => sum + r.judgmentAmount, 0),
    contingencyCount: contingency.length,
    contingencyValue: contingency.reduce((sum, r) => sum + r.judgmentAmount, 0),
    pendingCount: pending.length,
    lowPriorityCount: lowPriority.length,
    totalActionableValue,
    avgScore,
  };
}
