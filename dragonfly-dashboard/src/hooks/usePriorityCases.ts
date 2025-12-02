/**
 * usePriorityCases.ts
 * ────────────────────────────────────────────────────────────────────────────
 * Fetches top-priority cases (Tier A/B) for the "Today's Priorities" action list.
 * Returns data shaped for the ActionList component.
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
import type { ActionItem, ActionType } from '../components/dashboard/ActionList';
import { useOnRefresh } from '../context/RefreshContext';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

/** Raw row shape from v_collectability_snapshot */
interface CollectabilitySnapshotRow {
  case_id: string | null;
  case_number: string | null;
  judgment_amount: number | null;
  judgment_date: string | null;
  age_days: number | null;
  last_enriched_at: string | null;
  last_enrichment_status: string | null;
  collectability_tier: string | null;
  defendant_name?: string | null;
}

/** Priority case formatted for display */
export interface PriorityCase {
  caseId: string;
  caseNumber: string;
  defendantName: string | null;
  judgmentAmount: number | null;
  ageDays: number | null;
  tier: 'A' | 'B' | 'C';
  enrichmentStatus: string | null;
}

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function normalizeTier(tier: string | null): 'A' | 'B' | 'C' {
  if (tier === 'A' || tier === 'B') return tier;
  return 'C';
}

function determineActionType(enrichmentStatus: string | null): ActionType {
  const status = (enrichmentStatus ?? '').toLowerCase();
  
  if (status.includes('pending') || status.includes('needs')) {
    return 'file';  // File action for cases needing enrichment
  }
  if (status.includes('ready') || status.includes('complete')) {
    return 'review';
  }
  return 'follow_up';
}

function determineUrgency(tier: 'A' | 'B' | 'C', ageDays: number | null): 'overdue' | 'high' | 'normal' {
  if (tier === 'A') return 'overdue';  // Tier A = highest urgency (overdue styling)
  if (tier === 'B' && ageDays !== null && ageDays > 30) return 'high';
  return 'normal';
}

function buildActionTitle(caseNumber: string, enrichmentStatus: string | null): string {
  const status = (enrichmentStatus ?? '').toLowerCase();
  
  if (status.includes('pending') || status.includes('needs')) {
    return `Enrich case ${caseNumber}`;
  }
  if (status.includes('ready') || status.includes('complete')) {
    return `Review ${caseNumber} for enforcement`;
  }
  return `Follow up on ${caseNumber}`;
}

/** Convert raw rows to ActionItem[] for ActionList */
export function toActionItems(cases: PriorityCase[]): ActionItem[] {
  return cases.map((c) => ({
    id: c.caseId,
    type: determineActionType(c.enrichmentStatus),
    title: buildActionTitle(c.caseNumber, c.enrichmentStatus),
    caseNumber: c.caseNumber,
    defendant: c.defendantName ?? undefined,
    amount: c.judgmentAmount ?? undefined,
    tier: c.tier,
    urgency: determineUrgency(c.tier, c.ageDays),
    completed: false,
  }));
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

const DEFAULT_LIMIT = 5;

export function usePriorityCases(limit: number = DEFAULT_LIMIT): MetricsHookResult<PriorityCase[]> {
  const [state, setState] = useState<MetricsState<PriorityCase[]>>(() =>
    buildInitialMetricsState<PriorityCase[]>()
  );

  const fetchPriorityCases = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setState(buildDemoLockedState<PriorityCase[]>());
      return;
    }

    setState((prev) => buildLoadingMetricsState(prev));

    try {
      // Query top priority cases (Tier A and B, ordered by judgment amount)
      const result = await demoSafeSelect<CollectabilitySnapshotRow[] | null>(
        supabaseClient
          .from('v_collectability_snapshot')
          .select('case_id, case_number, judgment_amount, judgment_date, age_days, last_enriched_at, last_enrichment_status, collectability_tier')
          .in('collectability_tier', ['A', 'B'])
          .order('judgment_amount', { ascending: false, nullsFirst: false })
          .limit(limit)
      );

      if (result.kind === 'demo_locked') {
        setState(buildDemoLockedState<PriorityCase[]>());
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const rows = (result.data ?? []) as CollectabilitySnapshotRow[];

      const priorityCases: PriorityCase[] = rows.map((row) => ({
        caseId: row.case_id ?? '',
        caseNumber: row.case_number ?? '—',
        defendantName: row.defendant_name ?? null,
        judgmentAmount: row.judgment_amount,
        ageDays: row.age_days,
        tier: normalizeTier(row.collectability_tier),
        enrichmentStatus: row.last_enrichment_status,
      }));

      setState(buildReadyMetricsState(priorityCases));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load priority cases';
      console.error('[usePriorityCases] Error:', message);
      setState(buildErrorMetricsState<PriorityCase[]>(message));
    }
  }, [limit]);

  useEffect(() => {
    fetchPriorityCases();
  }, [fetchPriorityCases]);

  // Subscribe to global refresh
  useOnRefresh(() => fetchPriorityCases());

  // Return both flat snapshot properties AND state for backward compat
  return {
    ...state,
    state,
    refetch: fetchPriorityCases,
  };
}

export default usePriorityCases;
