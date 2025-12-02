import { useCallback, useEffect, useState } from 'react';
import type { PostgrestError } from '@supabase/supabase-js';
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

export interface CaseInfo {
  caseId: string;
  caseNumber: string;
  plaintiffName: string | null;
  currentStage: string | null;
  status: string | null;
  assignedTo: string | null;
  judgmentAmount: number | null;
}

export interface CopilotSuggestion {
  title: string;
  rationale: string | null;
  nextStep: string | null;
}

export interface CopilotDraftPlan {
  title: string;
  objective: string | null;
  keyPoints: string[];
}

export interface CopilotTimelineInsight {
  observation: string;
  impact: string | null;
  urgency: string | null;
}

export interface CopilotContactStrategy {
  channel: string;
  action: string;
  cadence: string | null;
  notes: string | null;
}

export interface CaseCopilotInsight {
  caseId: string;
  caseNumber: string;
  summary: string | null;
  recommendedActions: string[];
  enforcementSuggestions: CopilotSuggestion[];
  draftDocuments: CopilotDraftPlan[];
  riskValue: number | null;
  riskLabel: string | null;
  riskDrivers: string[];
  timelineAnalysis: CopilotTimelineInsight[];
  contactStrategy: CopilotContactStrategy[];
  generatedAt: string | null;
  invocationStatus: string | null;
  errorMessage: string | null;
  model: string | null;
  env: string | null;
}

export interface CaseCopilotSnapshot {
  caseInfo: CaseInfo | null;
  insight: CaseCopilotInsight | null;
}

export type UseCaseCopilotInsightResult = MetricsHookResult<CaseCopilotSnapshot>;

const COPILOT_LOCK_MESSAGE = 'Case Copilot stays locked in this demo environment.';

export function useCaseCopilotInsight(caseNumber: string | null): UseCaseCopilotInsightResult {
  const [snapshot, setSnapshot] = useState<MetricsState<CaseCopilotSnapshot>>(() =>
    buildInitialMetricsState<CaseCopilotSnapshot>(),
  );

  const normalized = (caseNumber ?? '').trim();
  const targetCaseNumber = normalized.length > 0 ? normalized.toUpperCase() : null;

  const fetchData = useCallback(async () => {
    if (!targetCaseNumber) {
      setSnapshot(buildReadyMetricsState<CaseCopilotSnapshot>({ caseInfo: null, insight: null }));
      return;
    }

    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<CaseCopilotSnapshot>(COPILOT_LOCK_MESSAGE));
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      const [caseResult, copilotResult] = await Promise.all([
        demoSafeSelect<RawCaseSummaryRow[] | null>(
          supabaseClient
            .from('v_enforcement_case_summary')
            .select('case_id, case_number, plaintiff_name, current_stage, status, assigned_to, judgment_amount')
            .eq('case_number', targetCaseNumber)
            .limit(1),
        ),
        demoSafeSelect<RawCaseCopilotRow[] | null>(
          supabaseClient
            .from('v_case_copilot_latest')
            .select(
              'case_id, case_number, summary, recommended_actions, enforcement_suggestions, draft_documents, risk_value, risk_label, risk_drivers, timeline_analysis, contact_strategy, generated_at, invocation_status, error_message, model, env',
            )
            .eq('case_number', targetCaseNumber)
            .limit(1),
        ),
      ]);

      if (caseResult.kind === 'demo_locked' || copilotResult.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState<CaseCopilotSnapshot>(COPILOT_LOCK_MESSAGE));
        return;
      }

      if (caseResult.kind === 'error') {
        throw caseResult.error;
      }

      if (copilotResult.kind === 'error' && !isSchemaCacheMiss(copilotResult.error)) {
        throw copilotResult.error;
      }

      const caseRow = ((caseResult.data ?? [])[0] as RawCaseSummaryRow | undefined) ?? null;

      if (!caseRow) {
        setSnapshot(
          buildErrorMetricsState<CaseCopilotSnapshot>(new Error('Case not found in enforcement tracking.'), {
            message: 'Case not found in enforcement tracking.',
          }),
        );
        return;
      }

      const mappedCase = mapCaseSummaryRow(caseRow, targetCaseNumber);
      const copilotRow =
        copilotResult.kind === 'ok'
          ? (((copilotResult.data ?? [])[0] as RawCaseCopilotRow | undefined) ?? null)
          : null;
      const mappedInsight = copilotRow ? mapCopilotRow(copilotRow, targetCaseNumber) : null;

      setSnapshot(buildReadyMetricsState({ caseInfo: mappedCase, insight: mappedInsight }));
    } catch (err) {
      const normalized = err instanceof Error ? err : new Error('Failed to load Case Copilot data');
      const friendly = deriveCopilotErrorMessage(err) ?? normalized.message ?? 'Failed to load Case Copilot data';
      setSnapshot(
        buildErrorMetricsState<CaseCopilotSnapshot>(normalized, {
          message: friendly,
        }),
      );
    }
  }, [targetCaseNumber]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const refetch = useCallback(() => fetchData(), [fetchData]);

  return {
    ...snapshot,
    state: snapshot,
    refetch,
  } satisfies MetricsHookResult<CaseCopilotSnapshot>;
}

interface RawCaseSummaryRow {
  case_id: string | null;
  case_number: string | null;
  plaintiff_name: string | null;
  current_stage: string | null;
  status: string | null;
  assigned_to: string | null;
  judgment_amount: number | string | null;
}

interface RawCaseCopilotRow {
  case_id: string | null;
  case_number: string | null;
  summary: string | null;
  recommended_actions: unknown;
  enforcement_suggestions: unknown;
  draft_documents: unknown;
  risk_value: number | string | null;
  risk_label: string | null;
  risk_drivers: unknown;
  timeline_analysis: unknown;
  contact_strategy: unknown;
  generated_at: string | null;
  invocation_status: string | null;
  error_message: string | null;
  model: string | null;
  env: string | null;
}

function mapCaseSummaryRow(row: RawCaseSummaryRow, fallbackCaseNumber: string | null): CaseInfo {
  return {
    caseId: coerceString(row.case_id),
    caseNumber: coerceString(row.case_number, fallbackCaseNumber ?? '—'),
    plaintiffName: coerceString(row.plaintiff_name) || null,
    currentStage: coerceString(row.current_stage) || null,
    status: coerceString(row.status) || null,
    assignedTo: coerceString(row.assigned_to) || null,
    judgmentAmount: coerceNumber(row.judgment_amount),
  } satisfies CaseInfo;
}

function mapCopilotRow(row: RawCaseCopilotRow, fallbackCaseNumber: string | null): CaseCopilotInsight {
  return {
    caseId: coerceString(row.case_id),
    caseNumber: coerceString(row.case_number, fallbackCaseNumber ?? '—'),
    summary: coerceString(row.summary) || null,
    recommendedActions: coerceStringArray(row.recommended_actions),
    enforcementSuggestions: coerceSuggestionArray(row.enforcement_suggestions),
    draftDocuments: coerceDraftPlanArray(row.draft_documents),
    riskValue: coerceNumber(row.risk_value),
    riskLabel: coerceString(row.risk_label) || null,
    riskDrivers: coerceStringArray(row.risk_drivers),
    timelineAnalysis: coerceTimelineArray(row.timeline_analysis),
    contactStrategy: coerceContactArray(row.contact_strategy),
    generatedAt: coerceString(row.generated_at) || null,
    invocationStatus: coerceString(row.invocation_status) || null,
    errorMessage: coerceString(row.error_message) || null,
    model: coerceString(row.model) || null,
    env: coerceString(row.env) || null,
  } satisfies CaseCopilotInsight;
}

function coerceString(value: unknown, fallback = ''): string {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : fallback;
  }
  return fallback;
}

function coerceNumber(value: unknown): number | null {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return null;
}

function coerceStringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => (typeof item === 'string' ? item.trim() : String(item ?? '')).trim())
      .filter((entry) => entry.length > 0);
  }
  return [];
}

function coerceSuggestionArray(value: unknown): CopilotSuggestion[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const entries: CopilotSuggestion[] = [];
  for (const item of value) {
    if (!item || typeof item !== 'object') {
      continue;
    }
    const source = item as Record<string, unknown>;
    const title = coerceNullableString(source.title ?? source['title']);
    if (!title) {
      continue;
    }
    entries.push({
      title,
      rationale: coerceNullableString(source.rationale ?? source['rationale']) ?? null,
      nextStep: coerceNullableString(source.next_step ?? source.nextStep) ?? null,
    });
  }
  return entries;
}

function coerceDraftPlanArray(value: unknown): CopilotDraftPlan[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const rows: CopilotDraftPlan[] = [];
  for (const item of value) {
    if (!item || typeof item !== 'object') {
      continue;
    }
    const source = item as Record<string, unknown>;
    const title = coerceString(source.title, '');
    if (!title) {
      continue;
    }
    rows.push({
      title,
      objective: coerceNullableString(source.objective) ?? null,
      keyPoints: coerceStringArray(source.key_points ?? source.keyPoints),
    });
  }
  return rows;
}

function coerceTimelineArray(value: unknown): CopilotTimelineInsight[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const insights: CopilotTimelineInsight[] = [];
  for (const item of value) {
    if (!item || typeof item !== 'object') {
      continue;
    }
    const source = item as Record<string, unknown>;
    const observation = coerceNullableString(source.observation);
    if (!observation) {
      continue;
    }
    insights.push({
      observation,
      impact: coerceNullableString(source.impact) ?? null,
      urgency: coerceNullableString(source.urgency) ?? null,
    });
  }
  return insights;
}

function coerceContactArray(value: unknown): CopilotContactStrategy[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const plays: CopilotContactStrategy[] = [];
  for (const item of value) {
    if (!item || typeof item !== 'object') {
      continue;
    }
    const source = item as Record<string, unknown>;
    const action = coerceNullableString(source.action);
    if (!action) {
      continue;
    }
    plays.push({
      channel: coerceNullableString(source.channel) ?? 'unspecified',
      action,
      cadence: coerceNullableString(source.cadence) ?? null,
      notes: coerceNullableString(source.notes) ?? null,
    });
  }
  return plays;
}

function coerceNullableString(value: unknown): string | null {
  const result = coerceString(value);
  return result.length > 0 ? result : null;
}

function deriveCopilotErrorMessage(err: unknown): string | null {
  if (!err) {
    return null;
  }
  if (isSchemaCacheMiss(err)) {
    return 'Case Copilot view is unavailable. Apply migrations and reload PostgREST.';
  }
  return null;
}

function isSchemaCacheMiss(err: unknown): err is PostgrestError {
  if (!err || typeof err !== 'object') {
    return false;
  }
  const maybe = err as PostgrestError & { status?: number };
  if (maybe.code === '42P01' || maybe.code === 'PGRST116') {
    return true;
  }
  const normalizedMessage = (maybe.message ?? '').toLowerCase();
  const normalizedDetails = (maybe.details ?? '').toLowerCase();
  if (maybe.status === 404) {
    return true;
  }
  return normalizedMessage.includes('schema cache') || normalizedDetails.includes('schema cache');
}
