import type { PostgrestError } from '@supabase/supabase-js';

export interface DashboardErrorPayload {
  error: Error;
  message: string;
}

interface BuildDashboardErrorOptions {
  fallback?: string;
  viewName?: string;
  actionHint?: string;
}

const DEFAULT_ACTION_HINT = 'Apply the latest Supabase migrations and reload the PostgREST schema cache.';
const DEFAULT_FALLBACK = 'Unable to load dashboard data.';

export function buildDashboardError(
  err: unknown,
  options: BuildDashboardErrorOptions = {},
): DashboardErrorPayload {
  const fallbackMessage = options.fallback ?? DEFAULT_FALLBACK;
  const normalizedError = err instanceof Error ? err : new Error(fallbackMessage);

  if (isSchemaCacheMiss(err)) {
    const viewLabel = options.viewName ?? 'A required Supabase view';
    const actionHint = options.actionHint ?? DEFAULT_ACTION_HINT;
    return {
      error: normalizedError,
      message: `${viewLabel} is unavailable. ${actionHint}`,
    } satisfies DashboardErrorPayload;
  }

  return {
    error: normalizedError,
    message: fallbackMessage,
  } satisfies DashboardErrorPayload;
}

export function isSchemaCacheMiss(err: unknown): err is PostgrestError | (Partial<PostgrestError> & { status?: number }) {
  if (!err || typeof err !== 'object') {
    return false;
  }
  const maybe = err as Partial<PostgrestError> & { status?: number };
  const code = maybe.code;
  if (code === '42P01' || code === 'PGRST116') {
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
