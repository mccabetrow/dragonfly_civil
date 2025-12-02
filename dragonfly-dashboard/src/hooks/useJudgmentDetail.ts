import { useCallback, useEffect, useMemo, useState } from 'react';
import { IS_DEMO_MODE, demoSafeSelect, supabaseClient, type DemoSafeResult } from '../lib/supabaseClient';
import { DEFAULT_DEMO_LOCK_MESSAGE } from './metricsState';
import { buildDashboardError, isSchemaCacheMiss } from '../utils/dashboardErrors';

export type JudgmentDetailState = 'idle' | 'loading' | 'ready' | 'not-found' | 'error' | 'demo_locked';

export interface JudgmentSummary {
  id: string;
  caseNumber: string | null;
  plaintiffId: string | null;
  plaintiffName: string;
  defendantName: string | null;
  county: string | null;
  state: string | null;
  judgmentAmount: number;
  enforcementStage: string | null;
  enforcementStageLabel: string | null;
  enforcementStageUpdatedAt: string | null;
  collectabilityTier: string | null;
  collectabilityAgeDays: number | null;
  lastEnrichedAt: string | null;
  lastEnrichmentStatus: string | null;
  priorityLevel: string;
  priorityLabel: string;
  priorityUpdatedAt: string | null;
  plaintiffStatus: string | null;
}

export interface EnforcementHistoryEntry {
  id: string;
  stage: string | null;
  stageLabel: string | null;
  note: string | null;
  changedAt: string | null;
  changedBy: string | null;
}

export interface PriorityHistoryEntry {
  id: string;
  priorityLevel: string;
  priorityLabel: string;
  note: string | null;
  changedAt: string | null;
  changedBy: string | null;
}

export interface JudgmentTaskRow {
  id: string;
  label: string;
  status: string;
  dueAt: string | null;
  createdAt: string | null;
  assignee: string | null;
  templateCode: string | null;
  stepType: string | null;
}

export interface JudgmentDetailData {
  summary: JudgmentSummary;
  enforcementHistory: EnforcementHistoryEntry[];
  priorityHistory: PriorityHistoryEntry[];
  tasks: JudgmentTaskRow[];
}

export interface UseJudgmentDetailResult {
  state: JudgmentDetailState;
  data: JudgmentDetailData | null;
  error: string | null;
  lockMessage?: string | null;
  refetch: () => Promise<void>;
}

interface RawPipelineRow {
  judgment_id: string | number | null;
  case_number: string | null;
  plaintiff_id: string | number | null;
  plaintiff_name: string | null;
  defendant_name: string | null;
  judgment_amount: number | string | null;
  enforcement_stage: string | null;
  enforcement_stage_updated_at: string | null;
  collectability_tier: string | null;
  collectability_age_days: number | string | null;
  last_enriched_at: string | null;
  last_enrichment_status: string | null;
}

interface RawPriorityRow {
  judgment_id: string | number | null;
  priority_level: string | null;
  stage: string | null;
  plaintiff_status: string | null;
}

interface RawEnforcementHistoryRow {
  id: string | number | null;
  stage: string | null;
  note: string | null;
  changed_at: string | null;
  changed_by: string | null;
}

interface RawPriorityHistoryRow {
  id: string | number | null;
  priority_level: string | null;
  note: string | null;
  changed_at: string | null;
  changed_by: string | null;
}

interface RawTaskRow {
  task_id: string | null;
  label: string | null;
  status: string | null;
  due_at: string | null;
  created_at: string | null;
  payload: unknown;
  template_code: string | null;
  step_type: string | null;
}

const PRIORITY_LABELS: Record<string, string> = {
  low: 'Low',
  normal: 'Normal',
  high: 'High',
  urgent: 'Urgent',
  on_hold: 'On hold',
};

const JUDGMENT_DETAIL_LOCK_MESSAGE =
  'Judgment-level detail stays hidden in demo tenants. Connect production Supabase credentials to review these enforcement records.';

export function useJudgmentDetail(judgmentIdParam?: string | null): UseJudgmentDetailResult {
  const [state, setState] = useState<JudgmentDetailState>('idle');
  const [data, setData] = useState<JudgmentDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lockMessage, setLockMessage] = useState<string | null>(null);

  const applyDemoLock = useCallback(
    (message?: string | null) => {
      setState('demo_locked');
      setData(null);
      setError(null);
      setLockMessage(message ?? JUDGMENT_DETAIL_LOCK_MESSAGE ?? DEFAULT_DEMO_LOCK_MESSAGE);
    },
    [],
  );

  const normalizedId = useMemo(() => {
    if (!judgmentIdParam) {
      return '';
    }
    const trimmed = judgmentIdParam.trim();
    return trimmed.length > 0 ? trimmed : '';
  }, [judgmentIdParam]);

  const loadDetail = useCallback(async () => {
    if (!normalizedId) {
      setState('not-found');
      setData(null);
      setError('Missing judgment id.');
      setLockMessage(null);
      return;
    }

    if (IS_DEMO_MODE) {
      applyDemoLock(JUDGMENT_DETAIL_LOCK_MESSAGE);
      return;
    }

    setState('loading');
    setError(null);
    setLockMessage(null);

    try {
      const pipelineQuery = supabaseClient
        .from('v_judgment_pipeline')
        .select(
          'judgment_id, case_number, plaintiff_id, plaintiff_name, defendant_name, judgment_amount, enforcement_stage, enforcement_stage_updated_at, collectability_tier, collectability_age_days, last_enriched_at, last_enrichment_status',
        )
        .eq('judgment_id', normalizedId)
        .limit(1);

      const priorityQuery = supabaseClient
        .from('v_priority_pipeline')
        .select('judgment_id, priority_level, stage, plaintiff_status')
        .eq('judgment_id', normalizedId)
        .limit(1);

      const enforcementHistoryQuery = supabaseClient
        .from('enforcement_history')
        .select('id, stage, note, changed_at, changed_by')
        .eq('judgment_id', normalizedId)
        .order('changed_at', { ascending: false, nullsFirst: false })
        .limit(50);

      const priorityHistoryQuery = supabaseClient
        .from('judgment_priority_history')
        .select('id, priority_level, note, changed_at, changed_by')
        .eq('judgment_id', normalizedId)
        .order('changed_at', { ascending: false, nullsFirst: false })
        .limit(50);

      const [pipelineRes, priorityRes, enforcementHistoryRes, priorityHistoryRes] = await Promise.all([
        demoSafeSelect<RawPipelineRow[] | null>(pipelineQuery),
        demoSafeSelect<RawPriorityRow[] | null>(priorityQuery),
        demoSafeSelect<RawEnforcementHistoryRow[] | null>(enforcementHistoryQuery),
        demoSafeSelect<RawPriorityHistoryRow[] | null>(priorityHistoryQuery),
      ]);

      if (pipelineRes.kind === 'demo_locked') {
        applyDemoLock(JUDGMENT_DETAIL_LOCK_MESSAGE);
        return;
      }

      if (pipelineRes.kind === 'error') {
        throw pipelineRes.error;
      }

      if (pipelineRes.kind !== 'ok') {
        throw new Error('Judgment detail request was blocked.');
      }

      const pipelineRow = extractFirst(pipelineRes.data) as RawPipelineRow | null;
      if (!pipelineRow) {
        setState('not-found');
        setData(null);
        setError('Judgment not found.');
        setLockMessage(null);
        return;
      }

      const caseNumber = normalizeOptional(pipelineRow.case_number);
      const tasksQuery = caseNumber
        ? supabaseClient
            .from('enforcement.tasks')
            .select('task_id, label, status, due_at, created_at, payload, template_code, step_type')
            .eq('case_number', caseNumber)
            .order('created_at', { ascending: false, nullsFirst: false })
        : null;

      const tasksRes = await (tasksQuery
        ? demoSafeSelect<RawTaskRow[] | null>(tasksQuery)
        : Promise.resolve<DemoSafeResult<RawTaskRow[] | null>>({ kind: 'ok', data: [] }));

      if (hasDemoLock(pipelineRes, priorityRes, enforcementHistoryRes, priorityHistoryRes, tasksRes)) {
        applyDemoLock(JUDGMENT_DETAIL_LOCK_MESSAGE);
        return;
      }

      const priorityRow = extractFirstFromResult<RawPriorityRow>(priorityRes, { allowMissing: true });
      const enforcementRows = coerceRows<RawEnforcementHistoryRow>(enforcementHistoryRes, { allowMissing: true });
      const priorityHistoryRows = coerceRows<RawPriorityHistoryRow>(priorityHistoryRes, { allowMissing: true });
      const taskRows = coerceRows<RawTaskRow>(tasksRes, { allowMissing: true });

      const summary: JudgmentSummary = {
        id: normalizeIdentifier(pipelineRow.judgment_id, normalizedId),
        caseNumber,
        plaintiffId: normalizeOptional(pipelineRow.plaintiff_id ? String(pipelineRow.plaintiff_id) : null),
        plaintiffName: normalizeName(pipelineRow.plaintiff_name),
        defendantName: normalizeOptional(pipelineRow.defendant_name),
        county: null,
        state: null,
        judgmentAmount: parseCurrency(pipelineRow.judgment_amount),
        enforcementStage: normalizeStageCode(pipelineRow.enforcement_stage),
        enforcementStageLabel: normalizeStageLabel(pipelineRow.enforcement_stage),
        enforcementStageUpdatedAt: pipelineRow.enforcement_stage_updated_at ?? null,
        collectabilityTier: normalizeOptional(pipelineRow.collectability_tier)
          ? String(pipelineRow.collectability_tier).toUpperCase()
          : null,
        collectabilityAgeDays: parseInteger(pipelineRow.collectability_age_days),
        lastEnrichedAt: pipelineRow.last_enriched_at ?? null,
        lastEnrichmentStatus: normalizeOptional(pipelineRow.last_enrichment_status),
        priorityLevel: normalizePriority(priorityRow?.priority_level),
        priorityLabel: formatPriorityLabel(priorityRow?.priority_level),
        priorityUpdatedAt: derivePriorityUpdatedAt(priorityHistoryRows),
        plaintiffStatus: normalizeOptional(priorityRow?.plaintiff_status),
      } satisfies JudgmentSummary;

      const enforcementHistory: EnforcementHistoryEntry[] = enforcementRows.map((row) => ({
        id: normalizeIdentifier(row.id, cryptoRandomId()),
        stage: normalizeStageCode(row.stage),
        stageLabel: normalizeStageLabel(row.stage),
        note: normalizeOptional(row.note),
        changedAt: row.changed_at ?? null,
        changedBy: normalizeOptional(row.changed_by),
      }));

      const priorityHistory: PriorityHistoryEntry[] = priorityHistoryRows.map((row) => ({
        id: normalizeIdentifier(row.id, cryptoRandomId()),
        priorityLevel: normalizePriority(row.priority_level),
        priorityLabel: formatPriorityLabel(row.priority_level),
        note: normalizeOptional(row.note),
        changedAt: row.changed_at ?? null,
        changedBy: normalizeOptional(row.changed_by),
      }));

      const tasks: JudgmentTaskRow[] = taskRows.map((row) => ({
        id: row.task_id ?? cryptoRandomId(),
        label: normalizeName(row.label),
        status: normalizeOptional(row.status) ?? 'unknown',
        dueAt: row.due_at ?? null,
        createdAt: row.created_at ?? null,
        assignee: extractAssignee(row.payload),
        templateCode: normalizeOptional(row.template_code),
        stepType: normalizeOptional(row.step_type),
      }));

      setData({ summary, enforcementHistory, priorityHistory, tasks });
      setState('ready');
      setLockMessage(null);
    } catch (err) {
      const { message } = buildDashboardError(err, {
        fallback: 'Failed to load judgment detail.',
        viewName: 'Judgment detail views',
      });
      setState('error');
      setData(null);
      setError(message);
      setLockMessage(null);
    }
  }, [normalizedId, applyDemoLock]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  const refetch = useCallback(async () => {
    await loadDetail();
  }, [loadDetail]);

  return {
    state,
    data,
    error,
    lockMessage,
    refetch,
  } satisfies UseJudgmentDetailResult;
}

function normalizeIdentifier(value: string | number | null, fallback: string): string {
  if (typeof value === 'string' && value.trim().length > 0) {
    return value.trim();
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return String(value);
  }
  return fallback;
}

function normalizeOptional(value: string | number | null | undefined): string | null {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? String(value) : null;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  return null;
}

function normalizeName(value: string | null | undefined): string {
  return normalizeOptional(value) ?? '—';
}

function parseCurrency(value: number | string | null): number {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 0;
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return 0;
}

function parseInteger(value: number | string | null): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return null;
}

function normalizeStageCode(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim().toLowerCase();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeStageLabel(value: string | null | undefined): string | null {
  const code = normalizeStageCode(value);
  if (!code) {
    return null;
  }
  switch (code) {
    case 'pre_enforcement':
      return 'Outreach';
    case 'paperwork_filed':
      return 'Enforcement planning';
    case 'levy_issued':
      return 'Levy issued';
    case 'waiting_payment':
      return 'Waiting on payment';
    case 'payment_plan':
      return 'Payment plan';
    case 'collected':
      return 'Collected';
    case 'closed_no_recovery':
      return 'Closed (no recovery)';
    default:
      return titleCase(code.replace(/[_-]+/g, ' '));
  }
}

function normalizePriority(value: string | null | undefined): string {
  if (!value) {
    return 'normal';
  }
  const normalized = value.trim().toLowerCase();
  return normalized.length > 0 ? normalized : 'normal';
}

function formatPriorityLabel(value: string | null | undefined): string {
  const normalized = normalizePriority(value);
  return PRIORITY_LABELS[normalized] ?? titleCase(normalized.replace(/[_-]+/g, ' '));
}

function derivePriorityUpdatedAt(rows: RawPriorityHistoryRow[]): string | null {
  if (!rows || rows.length === 0) {
    return null;
  }
  return rows[0]?.changed_at ?? null;
}

function extractAssignee(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const direct = record['assignee'];
  const assignedTo = record['assigned_to'];
  if (typeof direct === 'string' && direct.trim()) {
    return direct.trim();
  }
  if (typeof assignedTo === 'string' && assignedTo.trim()) {
    return assignedTo.trim();
  }
  return null;
}

function titleCase(value: string): string {
  return value.replace(/\b([a-z])/g, (match) => match.toUpperCase());
}

function cryptoRandomId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2);
}

function hasDemoLock(...results: Array<DemoSafeResult<unknown>>): boolean {
  return results.some((result) => result.kind === 'demo_locked');
}

function extractFirst<T>(rows: T[] | null | undefined): T | null {
  if (Array.isArray(rows) && rows.length > 0) {
    return rows[0] ?? null;
  }
  return null;
}

function coerceRows<T>(result: DemoSafeResult<T[] | null>, options?: { allowMissing?: boolean }): T[] {
  if (result.kind === 'demo_locked') {
    throw new Error('Demo-locked results must be handled before coercion.');
  }
  if (result.kind === 'ok') {
    return Array.isArray(result.data) ? (result.data as T[]) : [];
  }
  if (options?.allowMissing && isSchemaCacheMiss(result.error)) {
    return [];
  }
  throw result.error;
}

function extractFirstFromResult<T>(result: DemoSafeResult<T[] | null>, options?: { allowMissing?: boolean }): T | null {
  const rows = coerceRows(result, options);
  return rows.length > 0 ? rows[0] ?? null : null;
}
