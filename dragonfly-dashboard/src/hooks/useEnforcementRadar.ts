/**
 * useEnforcementRadar
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Supabase hook for the enforcement.v_radar view.
 * Returns prioritized buy/contingency candidates with collectability scores.
 */
import { useCallback, useEffect, useState } from 'react';
import { IS_DEMO_MODE, demoSafeSelect, supabaseClient } from '../lib/supabaseClient';
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
}

export interface RadarFilters {
  strategy?: OfferStrategy | 'ALL';
  minScore?: number;
  minAmount?: number;
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
      let query = supabaseClient
        .from('v_radar')
        .select(
          'id, case_number, plaintiff_name, defendant_name, judgment_amount, collectability_score, offer_strategy, court, county, judgment_date, created_at'
        )
        .order('collectability_score', { ascending: false, nullsFirst: false })
        .order('judgment_amount', { ascending: false });

      // Apply filters
      if (filters?.strategy && filters.strategy !== 'ALL') {
        query = query.eq('offer_strategy', filters.strategy);
      }
      if (filters?.minScore !== undefined && filters.minScore > 0) {
        query = query.gte('collectability_score', filters.minScore);
      }
      if (filters?.minAmount !== undefined && filters.minAmount > 0) {
        query = query.gte('judgment_amount', filters.minAmount);
      }

      const result = await demoSafeSelect<Array<Record<string, unknown>> | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState<RadarRow[]>());
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const rows = (result.data ?? []) as Array<Record<string, unknown>>;
      const normalized: RadarRow[] = rows.map((row) => ({
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
      }));

      setSnapshot(buildReadyMetricsState(normalized));
    } catch (err) {
      const error =
        err instanceof Error
          ? err
          : typeof err === 'string'
          ? err
          : new Error('Unable to load enforcement radar.');
      setSnapshot(
        buildErrorMetricsState<RadarRow[]>(error, {
          message: 'Unable to load enforcement radar. The v_radar view may not exist yet.',
        })
      );
    }
  }, [filters?.strategy, filters?.minScore, filters?.minAmount]);

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
