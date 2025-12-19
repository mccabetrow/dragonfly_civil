import type { PostgrestError } from '@supabase/supabase-js';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface DashboardErrorPayload {
  error: Error;
  message: string;
  severity: 'warning' | 'error' | 'info';
  actionHint?: string;
  code?: string;
}

export type ErrorSeverity = DashboardErrorPayload['severity'];

interface BuildDashboardErrorOptions {
  fallback?: string;
  viewName?: string;
  actionHint?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// ACTIONABLE ERROR MESSAGES
// ═══════════════════════════════════════════════════════════════════════════

interface ActionableErrorConfig {
  message: string;
  severity: ErrorSeverity;
  actionHint: string;
}

/**
 * Maps HTTP status codes and error types to actionable user messages.
 * These replace generic "Unable to load" with specific diagnostics.
 */
const ERROR_MAP: Record<string, ActionableErrorConfig> = {
  // Network / Infrastructure
  '0': {
    message: 'Network Error',
    severity: 'error',
    actionHint: 'Check your internet connection and try again.',
  },
  '502': {
    message: 'API Unreachable',
    severity: 'error',
    actionHint: 'Backend service may be restarting. Check System Status.',
  },
  '503': {
    message: 'Service Unavailable',
    severity: 'error',
    actionHint: 'Backend is temporarily overloaded. Retry in a moment.',
  },
  '504': {
    message: 'Gateway Timeout',
    severity: 'error',
    actionHint: 'Request took too long. Reduce date range or refresh.',
  },

  // Auth
  '401': {
    message: 'Unauthorized',
    severity: 'error',
    actionHint: 'Session expired. Verify your Vercel/API Key and reload.',
  },
  '403': {
    message: 'Access Denied',
    severity: 'error',
    actionHint: 'You lack permission for this resource. Contact admin.',
  },

  // Not Found / Empty
  '404': {
    message: 'Resource Not Found',
    severity: 'warning',
    actionHint: 'Endpoint or view missing. Enrichment may be pending.',
  },
  PGRST116: {
    message: 'View Not Found',
    severity: 'warning',
    actionHint: 'Supabase view missing. Run DB migrations & reload schema.',
  },
  '42P01': {
    message: 'Table/View Missing',
    severity: 'warning',
    actionHint: 'Database object not found. Apply latest migrations.',
  },

  // Rate Limiting
  '429': {
    message: 'Rate Limited',
    severity: 'warning',
    actionHint: 'Too many requests. Wait a moment and retry.',
  },

  // Server Errors
  '500': {
    message: 'Server Error',
    severity: 'error',
    actionHint: 'Backend encountered an error. Check logs or retry.',
  },
};

const DEFAULT_ERROR: ActionableErrorConfig = {
  message: 'Unable to load data',
  severity: 'error',
  actionHint: 'An unexpected error occurred. Please try again.',
};

/**
 * Extracts status code from various error shapes (fetch, Supabase, axios, etc.)
 */
function extractStatusCode(err: unknown): string | null {
  if (!err || typeof err !== 'object') return null;

  const maybeErr = err as Record<string, unknown>;

  // Direct status
  if (typeof maybeErr.status === 'number') {
    return String(maybeErr.status);
  }

  // Supabase PostgREST code
  if (typeof maybeErr.code === 'string') {
    return maybeErr.code;
  }

  // Axios-style response
  if (maybeErr.response && typeof maybeErr.response === 'object') {
    const resp = maybeErr.response as Record<string, unknown>;
    if (typeof resp.status === 'number') {
      return String(resp.status);
    }
  }

  // Network error (fetch failed)
  if (maybeErr.name === 'TypeError' && maybeErr.message === 'Failed to fetch') {
    return '0';
  }

  return null;
}

/**
 * Returns a user-friendly, actionable error message based on the error type.
 *
 * @example
 * const { message, actionHint, severity } = getFriendlyErrorMessage(err);
 * // message: "API Unreachable"
 * // actionHint: "Backend service may be restarting. Check System Status."
 * // severity: "error"
 */
export function getFriendlyErrorMessage(err: unknown): ActionableErrorConfig & { code: string | null } {
  const code = extractStatusCode(err);

  if (code && ERROR_MAP[code]) {
    return { ...ERROR_MAP[code], code };
  }

  // Check for schema cache miss patterns
  if (isSchemaCacheMiss(err)) {
    return { ...ERROR_MAP['PGRST116'], code: 'PGRST116' };
  }

  // Check for empty data (not an error, but no results)
  if (err && typeof err === 'object' && 'data' in err) {
    const data = (err as { data: unknown }).data;
    if (Array.isArray(data) && data.length === 0) {
      return {
        message: 'No Data Found',
        severity: 'info',
        actionHint: 'No records match. Enrichment may still be pending.',
        code: 'EMPTY',
      };
    }
  }

  return { ...DEFAULT_ERROR, code };
}

// ═══════════════════════════════════════════════════════════════════════════
// LEGACY EXPORTS (backwards compatibility)
// ═══════════════════════════════════════════════════════════════════════════

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
      severity: 'warning',
    } satisfies DashboardErrorPayload;
  }

  return {
    error: normalizedError,
    message: fallbackMessage,
    severity: 'error',
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
