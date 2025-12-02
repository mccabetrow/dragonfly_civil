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

export type PlaintiffStatusCode =
  | 'new'
  | 'contacted'
  | 'qualified'
  | 'sent_agreement'
  | 'signed'
  | 'lost'
  | 'unknown';

export type PipelineStageCode =
  | 'intake'
  | 'outreach'
  | 'enforcement_planning'
  | 'enforcement_active'
  | 'enriched'
  | 'collected'
  | 'other';

export interface PlaintiffWorkbenchRow {
  plaintiffId: string;
  plaintiffName: string;
  firmName: string;
  status: PlaintiffStatusCode;
  statusLabel: string;
  totalJudgmentAmount: number;
  caseCount: number;
  enforcementActiveCases: number;
  enforcementPlanningCases: number;
  outreachCases: number;
  collectedCases: number;
}

export type UsePlaintiffWorkbenchResult = MetricsHookResult<PlaintiffWorkbenchRow[]>;

interface RawOverviewRow {
  plaintiff_id: string | null;
  plaintiff_name: string | null;
  firm_name: string | null;
  status: string | null;
  total_judgment_amount: number | string | null;
  case_count: number | string | null;
}

interface RawPipelineRow {
  plaintiff_id: string | null;
  enforcement_stage: string | null;
}

interface PipelineAccumulator {
  enforcementActiveCases: number;
  enforcementPlanningCases: number;
  outreachCases: number;
  collectedCases: number;
}

const STATUS_LABELS: Record<PlaintiffStatusCode, string> = {
  new: 'New',
  contacted: 'Contacted',
  qualified: 'Qualified',
  sent_agreement: 'Sent agreement',
  signed: 'Signed',
  lost: 'Lost',
  unknown: 'Untracked',
};

const STATUS_NORMALIZATION: Record<string, PlaintiffStatusCode> = {
  new: 'new',
  contacted: 'contacted',
  qualified: 'qualified',
  sent_agreement: 'sent_agreement',
  signed: 'signed',
  lost: 'lost',
};

const INITIAL_PIPELINE_ACCUMULATOR: PipelineAccumulator = {
  enforcementActiveCases: 0,
  enforcementPlanningCases: 0,
  outreachCases: 0,
  collectedCases: 0,
};

export function usePlaintiffWorkbench(): UsePlaintiffWorkbenchResult {
  const [snapshot, setSnapshot] = useState<MetricsState<PlaintiffWorkbenchRow[]>>(() =>
    buildInitialMetricsState<PlaintiffWorkbenchRow[]>(),
  );

  const fetchPlaintiffs = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(
        buildDemoLockedState<PlaintiffWorkbenchRow[]>(
          'Plaintiff workbench is locked in this demo. Connect to production Supabase to see live exposure.',
        ),
      );
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      const overviewResult = await demoSafeSelect<RawOverviewRow[] | null>(
        supabaseClient
          .from('v_plaintiffs_overview')
          .select('plaintiff_id, plaintiff_name, firm_name, status, total_judgment_amount, case_count')
          .order('total_judgment_amount', { ascending: false, nullsFirst: false }),
      );

      if (overviewResult.kind === 'demo_locked') {
        setSnapshot(
          buildDemoLockedState<PlaintiffWorkbenchRow[]>(
            'Plaintiff workbench is locked in this demo. Connect to production Supabase to see live exposure.',
          ),
        );
        return;
      }

      if (overviewResult.kind === 'error') {
        throw overviewResult.error;
      }

      const overviewRows = (overviewResult.data ?? []) as RawOverviewRow[];
      const pipelineMap = await fetchPipelineCounts(overviewRows);

      const mapped = overviewRows.map((row) => {
        const plaintiffId = (row.plaintiff_id ?? '').toString();
        const statusInfo = normalizeStatus(row.status);
        const totals = pipelineMap.get(plaintiffId) ?? { ...INITIAL_PIPELINE_ACCUMULATOR };

        return {
          plaintiffId,
          plaintiffName: normalizeName(row.plaintiff_name),
          firmName: normalizeFirm(row.firm_name),
          status: statusInfo.code,
          statusLabel: statusInfo.label,
          totalJudgmentAmount: parseNumeric(row.total_judgment_amount),
          caseCount: parseInteger(row.case_count),
          enforcementActiveCases: totals.enforcementActiveCases,
          enforcementPlanningCases: totals.enforcementPlanningCases,
          outreachCases: totals.outreachCases,
          collectedCases: totals.collectedCases,
        } satisfies PlaintiffWorkbenchRow;
      });

      setSnapshot(buildReadyMetricsState(mapped));
    } catch (err) {
      const normalized = asError(err);
      const friendly = deriveWorkbenchErrorMessage(err) ?? normalized.message ?? 'Unable to load plaintiff workbench.';
      setSnapshot(
        buildErrorMetricsState<PlaintiffWorkbenchRow[]>(normalized, {
          message: friendly,
        }),
      );
    }
  }, []);

  useEffect(() => {
    void fetchPlaintiffs();
  }, [fetchPlaintiffs]);

  const refetch = useCallback(() => fetchPlaintiffs(), [fetchPlaintiffs]);

  return {
    ...snapshot,
    state: snapshot,
    refetch,
  } satisfies MetricsHookResult<PlaintiffWorkbenchRow[]>;
}

async function fetchPipelineCounts(rows: RawOverviewRow[]): Promise<Map<string, PipelineAccumulator>> {
  const ids = Array.from(
    new Set(
      rows
        .map((row) => row.plaintiff_id)
        .filter((value): value is string => typeof value === 'string' && value.trim().length > 0),
    ),
  );

  if (ids.length === 0) {
    return new Map();
  }

  try {
    const result = await demoSafeSelect<RawPipelineRow[] | null>(
      supabaseClient.from('v_judgment_pipeline').select('plaintiff_id, enforcement_stage').in('plaintiff_id', ids),
    );

    if (result.kind === 'demo_locked') {
      return new Map();
    }

    if (result.kind === 'error') {
      if (isMissingRelationError(result.error)) {
        return new Map();
      }
      throw result.error;
    }

    const pipelineRows = (result.data ?? []) as RawPipelineRow[];
    const pipelineMap = new Map<string, PipelineAccumulator>();

    for (const row of pipelineRows) {
      const plaintiffId = row.plaintiff_id;
      if (!plaintiffId) {
        continue;
      }

      const stage = normalizePipelineStage(row.enforcement_stage);
      if (stage === 'other') {
        continue;
      }

      const current = pipelineMap.get(plaintiffId) ?? { ...INITIAL_PIPELINE_ACCUMULATOR };

      switch (stage) {
        case 'enforcement_active':
          current.enforcementActiveCases += 1;
          break;
        case 'enforcement_planning':
          current.enforcementPlanningCases += 1;
          break;
        case 'outreach':
          current.outreachCases += 1;
          break;
        case 'collected':
          current.collectedCases += 1;
          break;
        default:
          break;
      }

      pipelineMap.set(plaintiffId, current);
    }

    return pipelineMap;
  } catch (err) {
    return new Map();
  }
}

function normalizeStatus(input: string | null): { code: PlaintiffStatusCode; label: string } {
  if (!input || input.trim().length === 0) {
    return { code: 'unknown', label: STATUS_LABELS.unknown };
  }
  const normalized = input.trim().toLowerCase();
  const code = STATUS_NORMALIZATION[normalized] ?? 'unknown';
  const label = code === 'unknown' ? titleCase(normalized.replace(/[_-]+/g, ' ')) : STATUS_LABELS[code];
  return { code, label: label || STATUS_LABELS.unknown };
}

function normalizeName(value: string | null): string {
  if (!value) {
    return '—';
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : '—';
}

function normalizeFirm(value: string | null): string {
  if (!value) {
    return '—';
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : '—';
}

function parseNumeric(value: number | string | null): number {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 0;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return 0;
}

function parseInteger(value: number | string | null): number {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 0;
  }
  if (typeof value === 'string') {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return 0;
}

function normalizePipelineStage(stage: string | null): PipelineStageCode {
  if (!stage) {
    return 'other';
  }
  const normalized = stage.trim().toLowerCase();
  if (!normalized) {
    return 'other';
  }
  switch (normalized) {
    case 'collected':
      return 'collected';
    case 'payment_plan':
    case 'waiting_payment':
    case 'levy_issued':
      return 'enforcement_active';
    case 'paperwork_filed':
    case 'closed_no_recovery':
      return 'enforcement_planning';
    case 'pre_enforcement':
      return 'outreach';
    default:
      return 'enforcement_planning';
  }
}

function titleCase(value: string): string {
  if (!value) {
    return STATUS_LABELS.unknown;
  }
  const lower = value.toLowerCase();
  return lower.replace(/(^|\s)([a-z])/g, (match) => match.toUpperCase());
}

function asError(value: unknown): Error {
  if (value instanceof Error) {
    return value;
  }
  if (value && typeof value === 'object' && 'message' in value && typeof (value as { message: unknown }).message === 'string') {
    return new Error((value as { message: string }).message);
  }
  if (typeof value === 'string') {
    return new Error(value);
  }
  return new Error('Unable to load plaintiffs right now.');
}

function isMissingRelationError(error: PostgrestError | Error): boolean {
  if (!error) {
    return false;
  }
  // Only PostgrestError has code/details/hint
  const pgError = error as PostgrestError;
  const normalizedMessage = (pgError.message ?? '').toLowerCase();
  const normalizedDetails = (pgError.details ?? '').toLowerCase();
  const normalizedHint = (pgError.hint ?? '').toLowerCase();
  if (pgError.code === '42P01' || pgError.code === 'PGRST116') {
    return true;
  }
  if (normalizedMessage.includes('schema cache') || normalizedDetails.includes('schema cache') || normalizedHint.includes('schema cache')) {
    return true;
  }
  const status = (pgError as unknown as { status?: number }).status;
  return status === 404;
}

function deriveWorkbenchErrorMessage(err: unknown): string | null {
  if (!err) {
    return null;
  }
  if (isSchemaCacheMiss(err)) {
    return 'Plaintiff views are not available yet. Make sure database migrations are applied and the schema cache is reloaded.';
  }
  return null;
}

function isSchemaCacheMiss(err: unknown): boolean {
  if (!err || typeof err !== 'object') {
    return false;
  }
  const maybe = err as Partial<PostgrestError> & { status?: number };
  const message = (maybe.message ?? '').toLowerCase();
  const details = (maybe.details ?? '').toLowerCase();
  const hint = (maybe.hint ?? '').toLowerCase();
  if (maybe.code === '42P01' || maybe.code === 'PGRST116') {
    return true;
  }
  if (maybe.status === 404) {
    return true;
  }
  return message.includes('schema cache') || details.includes('schema cache') || hint.includes('schema cache');
}
