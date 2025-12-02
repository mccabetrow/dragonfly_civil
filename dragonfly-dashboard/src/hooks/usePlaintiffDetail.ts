import { useCallback, useEffect, useMemo, useState } from 'react';
import { IS_DEMO_MODE, demoSafeSelect, supabaseClient, type DemoSafeResult } from '../lib/supabaseClient';
import type { PlaintiffStatusCode } from './usePlaintiffWorkbench';
import { DEFAULT_DEMO_LOCK_MESSAGE } from './metricsState';
import { buildDashboardError, isSchemaCacheMiss } from '../utils/dashboardErrors';

export type PlaintiffDetailState = 'idle' | 'loading' | 'ready' | 'not-found' | 'error' | 'demo_locked';

export interface PlaintiffContact {
  id: string;
  name: string;
  role: string | null;
  email: string | null;
  phone: string | null;
  createdAt: string | null;
}

export interface PlaintiffStatusEvent {
  id: string;
  status: string;
  statusLabel: string;
  note: string | null;
  changedAt: string | null;
  changedBy: string | null;
}

export interface PlaintiffJudgmentRow {
  judgmentId: string;
  caseNumber: string | null;
  defendantName: string | null;
  judgmentAmount: number | null;
  enforcementStage: string | null;
  enforcementStageLabel: string | null;
  enforcementStageUpdatedAt: string | null;
  collectabilityTier: string | null;
  collectabilityAgeDays: number | null;
  lastEnrichedAt: string | null;
  lastEnrichmentStatus: string | null;
  enforcementCaseId: string | null;
}

export interface PipelineSummary {
  enforcementActive: number;
  enforcementPlanning: number;
  outreach: number;
  collected: number;
}

export interface PlaintiffSummary {
  id: string;
  name: string;
  firmName: string | null;
  status: {
    code: PlaintiffStatusCode;
    label: string;
  };
  email: string | null;
  phone: string | null;
  totalJudgmentAmount: number;
  caseCount: number;
  createdAt: string | null;
  updatedAt: string | null;
  pipeline: PipelineSummary;
}

export interface PlaintiffDetailData {
  summary: PlaintiffSummary;
  contacts: PlaintiffContact[];
  judgments: PlaintiffJudgmentRow[];
  statusHistory: PlaintiffStatusEvent[];
}

export interface UsePlaintiffDetailResult {
  state: PlaintiffDetailState;
  data: PlaintiffDetailData | null;
  error: string | null;
  lockMessage?: string | null;
  refetch: () => Promise<void>;
}

interface RawPlaintiffRow {
  id: string;
  name: string | null;
  firm_name: string | null;
  email: string | null;
  phone: string | null;
  status: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface RawOverviewRow {
  plaintiff_id: string | null;
  total_judgment_amount: number | string | null;
  case_count: number | string | null;
}

interface RawContactRow {
  id: string | null;
  name: string | null;
  role: string | null;
  email: string | null;
  phone: string | null;
  created_at: string | null;
}

interface RawStatusHistoryRow {
  id: string | null;
  status: string | null;
  note: string | null;
  changed_at: string | null;
  changed_by: string | null;
}

interface RawJudgmentRow {
  judgment_id: string | null;
  case_number: string | null;
  defendant_name: string | null;
  judgment_amount: number | string | null;
  enforcement_stage: string | null;
  enforcement_stage_updated_at: string | null;
  collectability_tier: string | null;
  collectability_age_days: number | string | null;
  last_enriched_at: string | null;
  last_enrichment_status: string | null;
  enforcement_case_id: string | null;
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

const EMPTY_PIPELINE: PipelineSummary = {
  enforcementActive: 0,
  enforcementPlanning: 0,
  outreach: 0,
  collected: 0,
};

const PLAINTIFF_DETAIL_LOCK_MESSAGE =
  'Plaintiff-level detail stays hidden in demo tenants. Connect production Supabase credentials to review these records.';

export function usePlaintiffDetail(plaintiffIdParam?: string | null): UsePlaintiffDetailResult {
  const [state, setState] = useState<PlaintiffDetailState>('idle');
  const [data, setData] = useState<PlaintiffDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lockMessage, setLockMessage] = useState<string | null>(null);

  const applyDemoLock = useCallback(
    (message?: string | null) => {
      setState('demo_locked');
      setData(null);
      setError(null);
      setLockMessage(message ?? PLAINTIFF_DETAIL_LOCK_MESSAGE ?? DEFAULT_DEMO_LOCK_MESSAGE);
    },
    [],
  );

  const normalizedId = useMemo(() => {
    if (!plaintiffIdParam) {
      return '';
    }
    const trimmed = plaintiffIdParam.trim();
    return trimmed.length > 0 ? trimmed : '';
  }, [plaintiffIdParam]);

  const loadDetail = useCallback(async () => {
    if (!normalizedId) {
      setState('not-found');
      setData(null);
      setError('Missing plaintiff id.');
      setLockMessage(null);
      return;
    }

    if (IS_DEMO_MODE) {
      applyDemoLock(PLAINTIFF_DETAIL_LOCK_MESSAGE);
      return;
    }

    setState('loading');
    setError(null);
    setLockMessage(null);

    try {
      const detailQuery = supabaseClient
        .from('plaintiffs')
        .select('id, name, firm_name, email, phone, status, created_at, updated_at')
        .eq('id', normalizedId)
        .limit(1);

      const overviewQuery = supabaseClient
        .from('v_plaintiffs_overview')
        .select('plaintiff_id, total_judgment_amount, case_count')
        .eq('plaintiff_id', normalizedId)
        .limit(1);

      const contactsQuery = supabaseClient
        .from('plaintiff_contacts')
        .select('id, name, role, email, phone, created_at')
        .eq('plaintiff_id', normalizedId)
        .order('created_at', { ascending: true, nullsFirst: false });

      const statusHistoryQuery = supabaseClient
        .from('plaintiff_status_history')
        .select('id, status, note, changed_at, changed_by')
        .eq('plaintiff_id', normalizedId)
        .order('changed_at', { ascending: false, nullsFirst: false })
        .limit(50);

      const judgmentsQuery = supabaseClient
        .from('v_judgment_pipeline')
        .select(
          'judgment_id, case_number, defendant_name, judgment_amount, enforcement_stage, enforcement_stage_updated_at, collectability_tier, collectability_age_days, last_enriched_at, last_enrichment_status, enforcement_case_id',
        )
        .eq('plaintiff_id', normalizedId)
        .order('judgment_amount', { ascending: false, nullsFirst: false })
        .limit(100);

      const [detailRes, overviewRes, contactsRes, statusRes, judgmentsRes] = await Promise.all([
        demoSafeSelect<RawPlaintiffRow[] | null>(detailQuery),
        demoSafeSelect<RawOverviewRow[] | null>(overviewQuery),
        demoSafeSelect<RawContactRow[] | null>(contactsQuery),
        demoSafeSelect<RawStatusHistoryRow[] | null>(statusHistoryQuery),
        demoSafeSelect<RawJudgmentRow[] | null>(judgmentsQuery),
      ]);

      if (hasDemoLock(detailRes, overviewRes, contactsRes, statusRes, judgmentsRes)) {
        applyDemoLock(PLAINTIFF_DETAIL_LOCK_MESSAGE);
        return;
      }

      if (detailRes.kind === 'error') {
        throw detailRes.error;
      }
      if (detailRes.kind !== 'ok') {
        throw new Error('Plaintiff detail request was blocked.');
      }

      const detailRow = extractFirst(detailRes.data) as RawPlaintiffRow | null;
      if (!detailRow) {
        setState('not-found');
        setData(null);
        setError('Plaintiff not found.');
        setLockMessage(null);
        return;
      }

      if (overviewRes.kind === 'error') {
        throw overviewRes.error;
      }
      if (overviewRes.kind !== 'ok') {
        throw new Error('Plaintiff overview request was blocked.');
      }

      const overviewRow = extractFirst(overviewRes.data) as RawOverviewRow | null;

      const contactRows = coerceRows<RawContactRow>(contactsRes);
      const statusHistoryRows = coerceRows<RawStatusHistoryRow>(statusRes);
      const judgmentRows = coerceRows<RawJudgmentRow>(judgmentsRes, { allowMissing: true });

      const summary: PlaintiffSummary = {
        id: detailRow.id,
        name: normalizeName(detailRow.name),
        firmName: normalizeOptional(detailRow.firm_name),
        status: normalizeStatus(detailRow.status ?? null, statusHistoryRows[0]?.status ?? null),
        email: normalizeOptional(detailRow.email),
        phone: normalizeOptional(detailRow.phone),
        totalJudgmentAmount: parseCurrency(overviewRow?.total_judgment_amount ?? null),
        caseCount: parseInteger(overviewRow?.case_count ?? null),
        createdAt: detailRow.created_at,
        updatedAt: detailRow.updated_at,
        pipeline: summarizePipeline(judgmentRows),
      };

      const contacts: PlaintiffContact[] = contactRows.map((row) => ({
        id: (row.id ?? '').toString() || cryptoRandomId(),
        name: normalizeName(row.name),
        role: normalizeOptional(row.role),
        email: normalizeOptional(row.email),
        phone: normalizeOptional(row.phone),
        createdAt: row.created_at ?? null,
      }));

      const statusHistory: PlaintiffStatusEvent[] = statusHistoryRows.map((row) => ({
        id: (row.id ?? '').toString() || cryptoRandomId(),
        status: normalizeRawStatus(row.status),
        statusLabel: normalizeStatus(row.status, null).label,
        note: normalizeOptional(row.note),
        changedAt: row.changed_at ?? null,
        changedBy: normalizeOptional(row.changed_by),
      }));

      const judgments: PlaintiffJudgmentRow[] = judgmentRows.map((row) => ({
        judgmentId: (row.judgment_id ?? '').toString() || cryptoRandomId(),
        caseNumber: normalizeOptional(row.case_number),
        defendantName: normalizeOptional(row.defendant_name),
        judgmentAmount: parseCurrency(row.judgment_amount ?? null),
        enforcementStage: normalizeOptional(row.enforcement_stage),
        enforcementStageLabel: normalizeStage(row.enforcement_stage),
        enforcementStageUpdatedAt: row.enforcement_stage_updated_at ?? null,
        collectabilityTier: normalizeOptional(row.collectability_tier),
        collectabilityAgeDays: parseInteger(row.collectability_age_days ?? null),
        lastEnrichedAt: row.last_enriched_at ?? null,
        lastEnrichmentStatus: normalizeOptional(row.last_enrichment_status),
        enforcementCaseId: normalizeId(row.enforcement_case_id),
      }));

      setData({
        summary,
        contacts,
        judgments,
        statusHistory,
      });
      setState('ready');
      setLockMessage(null);
    } catch (err) {
      const { message } = buildDashboardError(err, {
        fallback: 'Failed to load plaintiff detail.',
        viewName: 'Plaintiff detail views',
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
  };
}

function normalizeName(value: string | null): string {
  if (!value) {
    return '—';
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : '—';
}

function normalizeOptional(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeId(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeStatus(primary: string | null, fallback: string | null): { code: PlaintiffStatusCode; label: string } {
  const resolved = normalizeRawStatus(primary) || normalizeRawStatus(fallback);
  if (!resolved) {
    return { code: 'unknown', label: STATUS_LABELS.unknown };
  }
  const code = STATUS_NORMALIZATION[resolved] ?? 'unknown';
  const label = code === 'unknown' ? titleCase(resolved.replace(/[_-]+/g, ' ')) : STATUS_LABELS[code];
  return { code, label: label || STATUS_LABELS.unknown };
}

function normalizeRawStatus(value: string | null): string {
  if (!value) {
    return '';
  }
  const trimmed = value.trim().toLowerCase();
  return trimmed;
}

function titleCase(value: string): string {
  return value.replace(/\b([a-z])/g, (match) => match.toUpperCase());
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

function parseInteger(value: number | string | null): number {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 0;
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return 0;
}

function normalizeStage(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const normalized = trimmed.toLowerCase();
  switch (normalized) {
    case 'levy_issued':
    case 'payment_plan':
    case 'waiting_payment':
      return 'Enforcement active';
    case 'pre_enforcement':
      return 'Outreach';
    case 'paperwork_filed':
      return 'Enforcement planning';
    case 'collected':
      return 'Collected';
    case 'closed_no_recovery':
      return 'Closed';
    default:
      return titleCase(trimmed.replace(/[_-]+/g, ' '));
  }
}

function summarizePipeline(rows: RawJudgmentRow[]): PipelineSummary {
  if (!rows || rows.length === 0) {
    return { ...EMPTY_PIPELINE };
  }
  const summary: PipelineSummary = { ...EMPTY_PIPELINE };
  for (const row of rows) {
    const normalized = normalizeRawStage(row.enforcement_stage);
    switch (normalized) {
      case 'levy_issued':
      case 'payment_plan':
      case 'waiting_payment':
        summary.enforcementActive += 1;
        break;
      case 'paperwork_filed':
      case 'closed_no_recovery':
        summary.enforcementPlanning += 1;
        break;
      case 'pre_enforcement':
        summary.outreach += 1;
        break;
      case 'collected':
        summary.collected += 1;
        break;
      default:
        break;
    }
  }
  return summary;
}

function normalizeRawStage(value: string | null): string {
  if (!value) {
    return '';
  }
  return value.trim().toLowerCase();
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
