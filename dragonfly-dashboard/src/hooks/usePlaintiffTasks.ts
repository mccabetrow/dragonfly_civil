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

export type PlaintiffTaskStatus = 'open' | 'in_progress' | 'done' | 'cancelled' | 'unknown';

export interface PlaintiffTask {
  id: string;
  plaintiffId: string;
  kind: string;
  status: PlaintiffTaskStatus;
  dueAt: string | null;
  completedAt: string | null;
  note: string | null;
  createdAt: string;
}

interface RawTask {
  id: string;
  plaintiff_id: string | null;
  kind: string | null;
  status: string | null;
  due_at: string | null;
  completed_at: string | null;
  note: string | null;
  created_at: string | null;
}

const OPEN_STATUSES = new Set(['open', 'in_progress']);
const KNOWN_STATUSES: Record<string, PlaintiffTaskStatus> = {
  open: 'open',
  in_progress: 'in_progress',
  done: 'done',
  cancelled: 'cancelled',
};

export function usePlaintiffTasks(plaintiffId: string | null | undefined): MetricsHookResult<PlaintiffTask[]> {
  const [snapshot, setSnapshot] = useState<MetricsState<PlaintiffTask[]>>(() =>
    buildInitialMetricsState<PlaintiffTask[]>(),
  );

  const fetchTasks = useCallback(async () => {
    if (!plaintiffId) {
      setSnapshot(buildReadyMetricsState<PlaintiffTask[]>([]));
      return;
    }

    if (IS_DEMO_MODE) {
      setSnapshot(
        buildDemoLockedState<PlaintiffTask[]>(
          'Tasks stay hidden in the demo tenant. Connect to production Supabase to work items.',
        ),
      );
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      const query = supabaseClient
        .from('plaintiff_tasks')
        .select('id, plaintiff_id, kind, status, due_at, completed_at, note, created_at')
        .eq('plaintiff_id', plaintiffId);

      const result = await demoSafeSelect<RawTask[] | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(
          buildDemoLockedState<PlaintiffTask[]>(
            'Tasks stay hidden in the demo tenant. Connect to production Supabase to work items.',
          ),
        );
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const records = (result.data ?? []) as RawTask[];
      const mapped = records
        .map((row) => normalizeTask(row))
        .filter((task): task is PlaintiffTask => task !== null)
        .sort((a, b) => getSortValue(a) - getSortValue(b));

      setSnapshot(buildReadyMetricsState(mapped));
    } catch (err) {
      const normalizedError = err instanceof Error ? err : new Error('Failed to load tasks');
      const friendly = deriveTaskErrorMessage(err);
      setSnapshot(
        buildErrorMetricsState<PlaintiffTask[]>(normalizedError, {
          message: friendly ?? 'Unable to load tasks for this plaintiff.',
        }),
      );
    }
  }, [plaintiffId]);

  useEffect(() => {
    void fetchTasks();
  }, [fetchTasks]);

  const refetch = useCallback(() => fetchTasks(), [fetchTasks]);

  return {
    ...snapshot,
    state: snapshot,
    refetch,
  };
}

function normalizeTask(row: RawTask): PlaintiffTask | null {
  const id = row.id;
  const plaintiffId = row.plaintiff_id ?? '';
  if (!id || !plaintiffId) {
    return null;
  }

  const createdAt = row.created_at ?? new Date().toISOString();
  return {
    id,
    plaintiffId,
    kind: normalizeText(row.kind),
    status: normalizeStatus(row.status),
    dueAt: row.due_at,
    completedAt: row.completed_at,
    note: row.note,
    createdAt,
  } satisfies PlaintiffTask;
}

function normalizeText(value: string | null): string {
  if (!value) {
    return 'Uncategorized';
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : 'Uncategorized';
}

function normalizeStatus(value: string | null): PlaintiffTaskStatus {
  if (!value) {
    return 'unknown';
  }
  const normalized = value.trim().toLowerCase();
  return KNOWN_STATUSES[normalized] ?? 'unknown';
}

function getSortValue(task: PlaintiffTask): number {
  const dueValue = parseTimestamp(task.dueAt);
  const createdValue = parseTimestamp(task.createdAt);

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

function deriveTaskErrorMessage(err: unknown): string | null {
  if (!err) {
    return null;
  }
  if (isSchemaCacheMiss(err)) {
    return 'Plaintiff tasks table is unavailable. Apply latest migrations and refresh the PostgREST schema cache.';
  }
  if (typeof err === 'object' && err && 'message' in err && typeof (err as { message?: unknown }).message === 'string') {
    return (err as { message?: string }).message ?? null;
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

export function isTaskOpen(status: PlaintiffTaskStatus): boolean {
  return OPEN_STATUSES.has(status);
}