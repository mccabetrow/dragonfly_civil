/**
 * useCasesDashboard
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Fetches the cases/judgment pipeline via apiClient.
 * Returns CasesDashboardRow[] for the Cases table.
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

export interface CasesDashboardRow {
  judgmentId: string;
  caseNumber: string;
  plaintiffName: string;
  defendantName: string;
  judgmentAmount: number | null;
  collectabilityTier: string | null;
  collectabilityTierLabel: string;
  collectabilityAgeDays: number | null;
  enforcementStage: string | null;
  enforcementStageLabel: string;
  enforcementStageUpdatedIso: string | null;
  lastEnrichedAtIso: string | null;
  lastEnrichmentStatus: string | null;
  lastEnrichmentStatusLabel: string;
}

interface ApiJudgmentPipelineRow {
  judgment_id: string | null;
  case_number: string | null;
  plaintiff_name: string | null;
  defendant_name: string | null;
  judgment_amount: number | null;
  enforcement_stage: string | null;
  enforcement_stage_updated_at: string | null;
  collectability_tier: string | null;
  collectability_age_days: number | null;
  last_enriched_at: string | null;
  last_enrichment_status: string | null;
}

export interface CasesDashboardPayload {
  rows: CasesDashboardRow[];
  totalCount: number;
}

export function useCasesDashboard(): MetricsHookResult<CasesDashboardPayload> {
  const [snapshot, setSnapshot] = useState<MetricsState<CasesDashboardPayload>>(() =>
    buildInitialMetricsState<CasesDashboardPayload>(),
  );

  const fetchCases = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<CasesDashboardPayload>());
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      const pipelineRows = await apiClient.get<ApiJudgmentPipelineRow[]>('/api/v1/cases/pipeline');

      const mappedRows: CasesDashboardRow[] = (pipelineRows ?? []).map((row) => {
        const stage = normalizeStage(row.enforcement_stage);
        const tier = row.collectability_tier ?? null;
        const enrichmentStatus = normalizeStage(row.last_enrichment_status);

        return {
          judgmentId: row.judgment_id ?? '—',
          caseNumber: formatCaseNumber(row.case_number),
          plaintiffName: row.plaintiff_name ? row.plaintiff_name : '—',
          defendantName: row.defendant_name ? row.defendant_name : '—',
          judgmentAmount: parseNullableNumber(row.judgment_amount),
          collectabilityTier: tier,
          collectabilityTierLabel: humanizeCollectabilityTier(tier),
          collectabilityAgeDays: parseNullableNumber(row.collectability_age_days),
          enforcementStage: stage,
          enforcementStageLabel: humanizeEnforcementStage(stage),
          enforcementStageUpdatedIso: row.enforcement_stage_updated_at ?? null,
          lastEnrichedAtIso: row.last_enriched_at ?? null,
          lastEnrichmentStatus: row.last_enrichment_status ?? null,
          lastEnrichmentStatusLabel: humanizeEnrichmentStatus(enrichmentStatus),
        };
      });

      setSnapshot(buildReadyMetricsState<CasesDashboardPayload>({ rows: mappedRows, totalCount: mappedRows.length }));
    } catch (err) {
      console.error('[useCasesDashboard]', err);

      if (err instanceof AuthError) {
        setSnapshot(
          buildErrorMetricsState<CasesDashboardPayload>(err, {
            message: 'Invalid API key – check Vercel VITE_DRAGONFLY_API_KEY vs Railway DRAGONFLY_API_KEY.',
            isAuthError: true,
          })
        );
      } else if (err instanceof NotFoundError) {
        setSnapshot(
          buildErrorMetricsState<CasesDashboardPayload>(err, {
            message: 'Metrics/view not configured yet.',
            isNotFound: true,
          })
        );
      } else {
        const error = err instanceof Error ? err : new Error('We hit a snag while loading cases.');
        setSnapshot(
          buildErrorMetricsState<CasesDashboardPayload>(error, {
            message: 'Unable to load cases. Please try again.',
          })
        );
      }
    }
  }, []);

  useEffect(() => {
    void fetchCases();
  }, [fetchCases]);

  const refetch = useCallback(() => fetchCases(), [fetchCases]);

  return { ...snapshot, state: snapshot, refetch };
}

function parseNullableNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return null;
}

function formatCaseNumber(value: string | null): string {
  if (!value) {
    return '—';
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : '—';
}

function humanizeCollectabilityTier(tier: string | null): string {
  if (!tier) {
    return 'Not scored';
  }
  const normalized = tier.trim().toLowerCase();
  switch (normalized) {
    case 'tier_1':
    case 'tier1':
      return 'Tier 1';
    case 'tier_2':
    case 'tier2':
      return 'Tier 2';
    case 'tier_3':
    case 'tier3':
      return 'Tier 3';
    case 'tier_4':
    case 'tier4':
      return 'Tier 4';
    case 'tier_5':
    case 'tier5':
      return 'Tier 5';
    case 'unscored':
      return 'Not scored';
    default:
      return titleCase(normalized.replace(/[_-]+/g, ' '));
  }
}

function humanizeEnforcementStage(stage: string | null): string {
  const normalized = normalizeStage(stage);
  if (!normalized) {
    return 'Pre-enforcement';
  }
  switch (normalized) {
    case 'pre_enforcement':
      return 'Pre-enforcement';
    case 'paperwork_filed':
      return 'Paperwork filed';
    case 'levy_issued':
      return 'Levy issued';
    case 'waiting_payment':
      return 'Awaiting payment';
    case 'payment_plan':
      return 'Payment plan';
    case 'collected':
      return 'Collected';
    case 'closed_no_recovery':
      return 'Closed - no recovery';
    default:
      return titleCase(normalized.replace(/[_-]+/g, ' '));
  }
}

function humanizeEnrichmentStatus(status: string | null): string {
  if (!status) {
    return 'Not enriched';
  }
  const normalized = status.trim().toLowerCase();
  switch (normalized) {
    case 'enriched':
      return 'Enriched';
    case 'pending_enrichment':
    case 'enrich_pending':
      return 'Enrichment in progress';
    case 'enrich_failed':
      return 'Needs review';
    case 'outreach_ready':
      return 'Outreach ready';
    default:
      return titleCase(normalized.replace(/[_-]+/g, ' '));
  }
}

function normalizeStage(stage: string | null | undefined): string | null {
  if (!stage) {
    return null;
  }
  const normalized = stage.trim().toLowerCase();
  return normalized.length > 0 ? normalized : null;
}

function titleCase(value: string): string {
  return value.replace(/\b([a-z])/g, (match) => match.toUpperCase());
}
