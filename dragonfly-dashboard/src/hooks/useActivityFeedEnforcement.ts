/**
 * Hook for v_enforcement_actions_recent view
 * Shows recent enforcement activity for the activity feed
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

export interface ActivityFeedRow {
  actionId: string;
  judgmentId: string;
  caseIndexNumber: string;
  debtorName: string;
  actionType: string;
  status: string;
  requiresAttorneySignature: boolean;
  generatedUrl: string | null;
  notes: string | null;
  createdAt: string;
  updatedAt: string | null;
  principalAmount: number;
  collectabilityScore: number | null;
  judgmentStatus: string;
}

interface RawActivityRow {
  action_id: string | null;
  judgment_id: string | null;
  case_index_number: string | null;
  debtor_name: string | null;
  action_type: string | null;
  status: string | null;
  requires_attorney_signature: boolean | null;
  generated_url: string | null;
  notes: string | null;
  created_at: string | null;
  updated_at: string | null;
  principal_amount: number | string | null;
  collectability_score: number | string | null;
  judgment_status: string | null;
}

const ACTIVITY_VIEW = 'v_enforcement_actions_recent' as const;
const ACTIVITY_LOCK_MESSAGE =
  'Activity feed is hidden in demo mode. Connect to production tenant to view recent actions.';

function parseRow(raw: RawActivityRow): ActivityFeedRow | null {
  if (!raw.action_id || !raw.judgment_id) return null;

  return {
    actionId: raw.action_id,
    judgmentId: raw.judgment_id,
    caseIndexNumber: raw.case_index_number ?? '—',
    debtorName: raw.debtor_name ?? 'Unknown',
    actionType: raw.action_type ?? 'unknown',
    status: raw.status ?? 'unknown',
    requiresAttorneySignature: raw.requires_attorney_signature ?? false,
    generatedUrl: raw.generated_url ?? null,
    notes: raw.notes ?? null,
    createdAt: raw.created_at ?? new Date().toISOString(),
    updatedAt: raw.updated_at ?? null,
    principalAmount: typeof raw.principal_amount === 'number' ? raw.principal_amount : parseFloat(String(raw.principal_amount)) || 0,
    collectabilityScore: raw.collectability_score != null ? Number(raw.collectability_score) : null,
    judgmentStatus: raw.judgment_status ?? 'unknown',
  };
}

export type UseActivityFeedEnforcementResult = MetricsHookResult<ActivityFeedRow[]> & {
  todayCount: number;
};

export function useActivityFeedEnforcement(): UseActivityFeedEnforcementResult {
  const [state, setState] = useState<MetricsState<ActivityFeedRow[]>>(buildInitialMetricsState());

  const fetchData = useCallback(async () => {
    setState(buildLoadingMetricsState());

    if (IS_DEMO_MODE) {
      setState(buildDemoLockedState(ACTIVITY_LOCK_MESSAGE));
      return;
    }

    try {
      const query = supabaseClient
        .from(ACTIVITY_VIEW)
        .select('*')
        .order('created_at', { ascending: false })
        .limit(50);

      const result = await demoSafeSelect<RawActivityRow[]>(query);

      if (result.kind === 'demo_locked') {
        setState(buildDemoLockedState(ACTIVITY_LOCK_MESSAGE));
        return;
      }

      if (result.kind === 'error') {
        setState(buildErrorMetricsState(result.error.message));
        return;
      }

      const rows = result.data
        .map((r: RawActivityRow) => parseRow(r))
        .filter((r): r is ActivityFeedRow => r !== null);

      setState(buildReadyMetricsState(rows));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load activity feed';
      setState(buildErrorMetricsState(message));
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const rows = state.data ?? [];
  const today = new Date().toISOString().split('T')[0];
  const todayCount = rows.filter((r) => r.createdAt.startsWith(today)).length;

  return {
    ...state,
    state,
    data: rows,
    refetch: fetchData,
    todayCount,
  };
}

export const ACTION_STATUS_COLORS: Record<string, string> = {
  planned: 'bg-slate-100 text-slate-600',
  pending: 'bg-amber-100 text-amber-700',
  completed: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-red-100 text-red-700',
};

export const ACTION_TYPE_ICONS: Record<string, string> = {
  wage_garnishment: '💰',
  bank_levy: '🏦',
  property_lien: '🏠',
  information_subpoena: '📋',
  restraining_notice: '⚠️',
  other: '📄',
};
