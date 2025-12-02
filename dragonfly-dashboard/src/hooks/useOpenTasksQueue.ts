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

export interface OpenTaskQueueRow {
  taskId: string;
  plaintiffId: string;
  plaintiffName: string;
  firmName: string | null;
  kind: string;
  status: string;
  dueAt: string | null;
  createdAt: string | null;
  note: string | null;
}

interface RawQueueRow {
  task_id: string | null;
  plaintiff_id: string | null;
  plaintiff_name: string | null;
  firm_name: string | null;
  kind: string | null;
  status: string | null;
  due_at: string | null;
  created_at: string | null;
  note: string | null;
}

const TASK_QUEUE_LOCK_MESSAGE =
  'Task queue metrics stay hidden in this demo tenant. Connect production Supabase credentials to work live tasks.';

export function useOpenTasksQueue(limit: number = 25): MetricsHookResult<OpenTaskQueueRow[]> {
  const [snapshot, setSnapshot] = useState<MetricsState<OpenTaskQueueRow[]>>(() =>
    buildInitialMetricsState<OpenTaskQueueRow[]>(),
  );

  const fetchQueue = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<OpenTaskQueueRow[]>(TASK_QUEUE_LOCK_MESSAGE));
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));
    try {
      let query = supabaseClient
        .from('v_plaintiff_open_tasks')
        .select('task_id, plaintiff_id, plaintiff_name, firm_name, kind, status, due_at, created_at, note');

      if (Number.isFinite(limit) && limit > 0) {
        query = query.limit(limit);
      }

      const result = await demoSafeSelect<RawQueueRow[] | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState<OpenTaskQueueRow[]>(TASK_QUEUE_LOCK_MESSAGE));
        return;
      }

      if (result.kind === 'error') {
        logQueueError(result.error, setSnapshot);
        return;
      }

      const mapped = ((result.data ?? []) as RawQueueRow[])
        .map((row) => normalizeRow(row))
        .filter((row): row is OpenTaskQueueRow => row !== null)
        .sort((a, b) => getSortValue(a) - getSortValue(b));

      setSnapshot(buildReadyMetricsState(mapped));
    } catch (err) {
      const { normalizedError, friendlyMessage } = buildQueueErrorPayload(err);
      setSnapshot(buildErrorMetricsState<OpenTaskQueueRow[]>(normalizedError, { message: friendlyMessage }));
    }
  }, [limit]);

  useEffect(() => {
    void fetchQueue();
  }, [fetchQueue]);

  const refetch = useCallback(() => fetchQueue(), [fetchQueue]);

  return { ...snapshot, state: snapshot, refetch };
}

function normalizeRow(row: RawQueueRow): OpenTaskQueueRow | null {
  const taskId = row.task_id;
  const plaintiffId = row.plaintiff_id;
  if (!taskId || !plaintiffId) {
    return null;
  }
  return {
    taskId,
    plaintiffId,
    plaintiffName: normalizeText(row.plaintiff_name) ?? '—',
    firmName: normalizeNullable(row.firm_name),
    kind: normalizeText(row.kind) ?? 'Task',
    status: normalizeStatus(row.status),
    dueAt: row.due_at,
    createdAt: row.created_at,
    note: row.note,
  } satisfies OpenTaskQueueRow;
}

function normalizeText(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeNullable(value: string | null): string | null {
  const normalized = normalizeText(value);
  return normalized ?? null;
}

function normalizeStatus(value: string | null): string {
  if (!value) {
    return 'open';
  }
  const trimmed = value.trim().toLowerCase();
  return trimmed.length > 0 ? trimmed : 'open';
}

function getSortValue(row: OpenTaskQueueRow): number {
  const dueValue = parseTimestamp(row.dueAt);
  const createdValue = parseTimestamp(row.createdAt);
  if (Number.isFinite(dueValue)) {
    return dueValue;
  }
  if (Number.isFinite(createdValue)) {
    return createdValue;
  }
  return Number.POSITIVE_INFINITY;
}

function parseTimestamp(value: string | null): number {
  if (!value) {
    return Number.POSITIVE_INFINITY;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? Number.POSITIVE_INFINITY : parsed;
}

function deriveQueueErrorMessage(err: unknown): string | null {
  if (!err) {
    return null;
  }
  if (isSchemaCacheMiss(err)) {
    return 'Open tasks view is unavailable. Apply latest migrations and refresh the PostgREST schema cache.';
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

function logQueueError(
  error: PostgrestError | Error,
  setSnapshot: (state: MetricsState<OpenTaskQueueRow[]>) => void,
): void {
  const { normalizedError, friendlyMessage } = buildQueueErrorPayload(error);
  setSnapshot(buildErrorMetricsState<OpenTaskQueueRow[]>(normalizedError, { message: friendlyMessage }));
}

function buildQueueErrorPayload(error: unknown): { normalizedError: Error; friendlyMessage: string } {
  const defaultMessage = 'Unable to load the task queue.';
  const friendlyMessage = deriveQueueErrorMessage(error) ?? defaultMessage;
  const normalizedError = error instanceof Error ? error : new Error(friendlyMessage);
  return { normalizedError, friendlyMessage };
}
