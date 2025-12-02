/**
 * Hook for v_enforcement_pipeline_status view
 * Shows where each judgment is in the enforcement flow
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

export type PipelineStage =
  | 'awaiting_enrichment'
  | 'awaiting_action_plan'
  | 'awaiting_signature'
  | 'actions_in_progress'
  | 'actions_complete'
  | 'closed'
  | 'unknown';

export interface EnforcementPipelineRow {
  judgmentId: string;
  caseIndexNumber: string;
  debtorName: string;
  principalAmount: number;
  judgmentDate: string | null;
  judgmentStatus: string;
  collectabilityScore: number | null;
  pipelineStage: PipelineStage;
  hasEmployerIntel: boolean;
  hasBankIntel: boolean;
  isBenefitsOnly: boolean;
  intelConfidence: number | null;
  incomeBand: string | null;
  totalActions: number;
  plannedActions: number;
  pendingActions: number;
  completedActions: number;
  awaitingSignature: number;
  actionTypes: string[];
  lastActionAt: string | null;
}

interface RawPipelineRow {
  judgment_id: string | null;
  case_index_number: string | null;
  debtor_name: string | null;
  principal_amount: number | string | null;
  judgment_date: string | null;
  judgment_status: string | null;
  collectability_score: number | string | null;
  pipeline_stage: string | null;
  has_employer_intel: boolean | null;
  has_bank_intel: boolean | null;
  is_benefits_only: boolean | null;
  intel_confidence: number | string | null;
  income_band: string | null;
  total_actions: number | string | null;
  planned_actions: number | string | null;
  pending_actions: number | string | null;
  completed_actions: number | string | null;
  awaiting_signature: number | string | null;
  action_types: string[] | null;
  last_action_at: string | null;
}

const PIPELINE_VIEW = 'v_enforcement_pipeline_status' as const;
const PIPELINE_LOCK_MESSAGE =
  'Pipeline status is hidden in demo mode. Connect to production tenant to view live data.';

const STAGE_ORDER: PipelineStage[] = [
  'awaiting_signature',
  'actions_in_progress',
  'awaiting_action_plan',
  'awaiting_enrichment',
  'actions_complete',
  'closed',
  'unknown',
];

export const STAGE_LABELS: Record<PipelineStage, string> = {
  awaiting_enrichment: 'Awaiting Enrichment',
  awaiting_action_plan: 'Needs Action Plan',
  awaiting_signature: 'Awaiting Signature',
  actions_in_progress: 'In Progress',
  actions_complete: 'Actions Complete',
  closed: 'Closed',
  unknown: 'Unknown',
};

export const STAGE_COLORS: Record<PipelineStage, string> = {
  awaiting_enrichment: 'bg-slate-100 text-slate-700',
  awaiting_action_plan: 'bg-amber-100 text-amber-700',
  awaiting_signature: 'bg-red-100 text-red-700',
  actions_in_progress: 'bg-blue-100 text-blue-700',
  actions_complete: 'bg-emerald-100 text-emerald-700',
  closed: 'bg-slate-200 text-slate-600',
  unknown: 'bg-slate-50 text-slate-500',
};

function parseRow(raw: RawPipelineRow): EnforcementPipelineRow | null {
  if (!raw.judgment_id) return null;

  return {
    judgmentId: raw.judgment_id,
    caseIndexNumber: raw.case_index_number ?? '—',
    debtorName: raw.debtor_name ?? 'Unknown',
    principalAmount: typeof raw.principal_amount === 'number' ? raw.principal_amount : parseFloat(String(raw.principal_amount)) || 0,
    judgmentDate: raw.judgment_date ?? null,
    judgmentStatus: raw.judgment_status ?? 'unknown',
    collectabilityScore: raw.collectability_score != null ? Number(raw.collectability_score) : null,
    pipelineStage: (raw.pipeline_stage as PipelineStage) ?? 'unknown',
    hasEmployerIntel: raw.has_employer_intel ?? false,
    hasBankIntel: raw.has_bank_intel ?? false,
    isBenefitsOnly: raw.is_benefits_only ?? false,
    intelConfidence: raw.intel_confidence != null ? Number(raw.intel_confidence) : null,
    incomeBand: raw.income_band ?? null,
    totalActions: Number(raw.total_actions) || 0,
    plannedActions: Number(raw.planned_actions) || 0,
    pendingActions: Number(raw.pending_actions) || 0,
    completedActions: Number(raw.completed_actions) || 0,
    awaitingSignature: Number(raw.awaiting_signature) || 0,
    actionTypes: raw.action_types ?? [],
    lastActionAt: raw.last_action_at ?? null,
  };
}

export interface PipelineFilters {
  stage: PipelineStage | 'all';
  minScore: number | null;
  minBalance: number | null;
}

export interface UseEnforcementPipelineOptions {
  filters?: Partial<PipelineFilters>;
  limit?: number;
}

export type UseEnforcementPipelineResult = MetricsHookResult<EnforcementPipelineRow[]> & {
  stageCounts: Record<PipelineStage, number>;
};

export function useEnforcementPipeline(
  options: UseEnforcementPipelineOptions = {},
): UseEnforcementPipelineResult {
  const { filters = {}, limit = 500 } = options;
  const [state, setState] = useState<MetricsState<EnforcementPipelineRow[]>>(buildInitialMetricsState());
  const [stageCounts, setStageCounts] = useState<Record<PipelineStage, number>>({
    awaiting_enrichment: 0,
    awaiting_action_plan: 0,
    awaiting_signature: 0,
    actions_in_progress: 0,
    actions_complete: 0,
    closed: 0,
    unknown: 0,
  });

  const fetchData = useCallback(async () => {
    setState(buildLoadingMetricsState());

    if (IS_DEMO_MODE) {
      setState(buildDemoLockedState(PIPELINE_LOCK_MESSAGE));
      return;
    }

    try {
      let query = supabaseClient
        .from(PIPELINE_VIEW)
        .select('*')
        .limit(limit);

      if (filters.stage && filters.stage !== 'all') {
        query = query.eq('pipeline_stage', filters.stage);
      }
      if (filters.minScore != null) {
        query = query.gte('collectability_score', filters.minScore);
      }
      if (filters.minBalance != null) {
        query = query.gte('principal_amount', filters.minBalance);
      }

      const result = await demoSafeSelect<RawPipelineRow[]>(query);

      if (result.kind === 'demo_locked') {
        setState(buildDemoLockedState(PIPELINE_LOCK_MESSAGE));
        return;
      }

      if (result.kind === 'error') {
        setState(buildErrorMetricsState(result.error.message));
        return;
      }

      const rows = result.data
        .map((r: RawPipelineRow) => parseRow(r))
        .filter((r): r is EnforcementPipelineRow => r !== null);

      // Calculate stage counts
      const counts: Record<PipelineStage, number> = {
        awaiting_enrichment: 0,
        awaiting_action_plan: 0,
        awaiting_signature: 0,
        actions_in_progress: 0,
        actions_complete: 0,
        closed: 0,
        unknown: 0,
      };
      for (const row of rows) {
        if (row.pipelineStage in counts) {
          counts[row.pipelineStage] = (counts[row.pipelineStage] || 0) + 1;
        }
      }
      setStageCounts(counts);

      setState(buildReadyMetricsState(rows));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load pipeline data';
      setState(buildErrorMetricsState(message));
    }
  }, [filters.stage, filters.minScore, filters.minBalance, limit]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  return {
    ...state,
    state,
    data: state.data ?? [],
    refetch: fetchData,
    stageCounts,
  };
}

export { STAGE_ORDER };
