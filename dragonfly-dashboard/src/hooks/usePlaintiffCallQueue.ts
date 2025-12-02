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

type PlaintiffStatusCode =
  | 'new'
  | 'contacted'
  | 'qualified'
  | 'sent_agreement'
  | 'signed'
  | 'lost'
  | 'unknown';

export interface PlaintiffCallQueueRow {
  plaintiffId: string;
  plaintiffName: string;
  firmName: string;
  status: PlaintiffStatusCode;
  statusLabel: string;
  totalJudgmentAmount: number;
  caseCount: number;
  lastContactedAt: string | null;
  phone: string | null;
  lastCallOutcome: string | null;
  lastCallAttemptedAt: string | null;
  lastCallNotes: string | null;
  createdAt: string | null;
}

interface RawQueueRow {
  plaintiff_id: string | null;
  plaintiff_name: string | null;
  firm_name: string | null;
  status: string | null;
  total_judgment_amount: number | string | null;
  case_count: number | string | null;
  last_contacted_at: string | null;
  phone: string | null;
  last_call_outcome: string | null;
  last_call_attempted_at: string | null;
  last_call_notes: string | null;
  created_at: string | null;
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

const CALL_QUEUE_LOCK_MESSAGE =
  'Detailed metrics are available only in the production enforcement console. This demo hides plaintiff-level collectability and executive metrics for safety.';

export function usePlaintiffCallQueue(limit: number = 25): MetricsHookResult<PlaintiffCallQueueRow[]> {
  const [snapshot, setSnapshot] = useState<MetricsState<PlaintiffCallQueueRow[]>>(() =>
    buildInitialMetricsState<PlaintiffCallQueueRow[]>(),
  );

  const fetchQueue = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<PlaintiffCallQueueRow[]>(CALL_QUEUE_LOCK_MESSAGE));
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));
    try {
      let query = supabaseClient
        .from('v_plaintiff_call_queue')
        .select(
          'plaintiff_id, plaintiff_name, firm_name, status, total_judgment_amount, case_count, last_contacted_at, phone, last_call_outcome, last_call_attempted_at, last_call_notes, created_at',
        );

      if (Number.isFinite(limit) && limit > 0) {
        query = query.limit(limit);
      }

      const result = await demoSafeSelect<RawQueueRow[] | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState<PlaintiffCallQueueRow[]>(CALL_QUEUE_LOCK_MESSAGE));
        return;
      }

      if (result.kind === 'error') {
        handleCallQueueError(result.error, setSnapshot);
        return;
      }

      const records = (result.data ?? []) as RawQueueRow[];
      const mapped = records.map((row) => {
        const plaintiffId = (row.plaintiff_id ?? '').toString();
        const statusInfo = normalizeStatus(row.status);
        return {
          plaintiffId,
          plaintiffName: normalizeName(row.plaintiff_name),
          firmName: normalizeFirm(row.firm_name),
          status: statusInfo.code,
          statusLabel: statusInfo.label,
          totalJudgmentAmount: parseNumber(row.total_judgment_amount),
          caseCount: parseInteger(row.case_count),
          lastContactedAt: row.last_contacted_at ?? null,
          phone: normalizePhone(row.phone),
          lastCallOutcome: normalizeString(row.last_call_outcome),
          lastCallAttemptedAt: row.last_call_attempted_at ?? null,
          lastCallNotes: normalizeString(row.last_call_notes),
          createdAt: row.created_at ?? null,
        } satisfies PlaintiffCallQueueRow;
      });

      setSnapshot(buildReadyMetricsState(mapped));
    } catch (err) {
      const { normalizedError, friendlyMessage } = buildCallQueueErrorPayload(err);
      setSnapshot(buildErrorMetricsState<PlaintiffCallQueueRow[]>(normalizedError, { message: friendlyMessage }));
    }
  }, [limit]);

  useEffect(() => {
    void fetchQueue();
  }, [fetchQueue]);

  const refetch = useCallback(() => fetchQueue(), [fetchQueue]);

  return { ...snapshot, state: snapshot, refetch };
}

function normalizeStatus(value: string | null): { code: PlaintiffStatusCode; label: string } {
  if (!value) {
    return { code: 'unknown', label: STATUS_LABELS.unknown };
  }
  const normalized = value.trim().toLowerCase();
  if (!normalized) {
    return { code: 'unknown', label: STATUS_LABELS.unknown };
  }
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

function normalizePhone(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeString(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function parseNumber(value: number | string | null): number {
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

function titleCase(value: string): string {
  return value.replace(/\b([a-z])/g, (match) => match.toUpperCase());
}

function deriveQueueErrorMessage(err: unknown): string | null {
  if (!err) {
    return null;
  }
  if (isSchemaCacheMiss(err)) {
    return 'Call queue view is unavailable. Apply latest migrations and refresh the PostgREST schema cache.';
  }
  return null;
}

function isSchemaCacheMiss(err: unknown): err is PostgrestError | (Partial<PostgrestError> & { status?: number }) {
  if (!err || typeof err !== 'object') {
    return false;
  }
  const maybe = err as Partial<PostgrestError> & { status?: number };
  if (maybe.code === '42P01' || maybe.code === 'PGRST116') {
    return true;
  }
  if (maybe.status === 404) {
    return true;
  }
  const message = (maybe.message ?? '').toLowerCase();
  const details = (maybe.details ?? '').toLowerCase();
  const hint = (maybe.hint ?? '').toLowerCase();
  return message.includes('schema cache') || details.includes('schema cache') || hint.includes('schema cache');
}

function handleCallQueueError(
  error: PostgrestError | Error,
  setSnapshot: (state: MetricsState<PlaintiffCallQueueRow[]>) => void,
): void {
  const { normalizedError, friendlyMessage } = buildCallQueueErrorPayload(error);
  setSnapshot(buildErrorMetricsState<PlaintiffCallQueueRow[]>(normalizedError, { message: friendlyMessage }));
}

function buildCallQueueErrorPayload(error: unknown): { normalizedError: Error; friendlyMessage: string } {
  const defaultMessage = 'Unable to load the call queue.';
  const friendlyMessage = deriveQueueErrorMessage(error) ?? defaultMessage;
  const normalizedError = error instanceof Error ? error : new Error(friendlyMessage);
  return { normalizedError, friendlyMessage };
}
