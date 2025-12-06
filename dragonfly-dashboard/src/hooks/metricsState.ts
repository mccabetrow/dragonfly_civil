export type MetricsStatus = 'idle' | 'loading' | 'ready' | 'demo_locked' | 'error';

export interface MetricsSnapshot<TData> {
  status: MetricsStatus;
  data: TData | null;
  error: Error | string | null;
  errorMessage: string | null;
  lockMessage?: string | null;
  /** True if error was AuthError (401/403) */
  isAuthError: boolean;
  /** True if error was NotFoundError (404) */
  isNotFound: boolean;
  /** True if error was a general API or network error */
  isError: boolean;
}

export type MetricsState<TData> = MetricsSnapshot<TData>;

export type MetricsHookResult<TData> = MetricsSnapshot<TData> & {
  state: MetricsState<TData>;
  refetch: () => Promise<void>;
};

export const DEFAULT_DEMO_LOCK_MESSAGE =
  'Detailed metrics are available only in the production enforcement console. This demo hides plaintiff-level and collectability data for safety.';

export function buildInitialMetricsState<TData>(): MetricsState<TData> {
  return {
    status: 'idle',
    data: null,
    error: null,
    errorMessage: null,
    lockMessage: null,
    isAuthError: false,
    isNotFound: false,
    isError: false,
  } satisfies MetricsState<TData>;
}

export function buildLoadingMetricsState<TData>(previous?: MetricsState<TData>): MetricsState<TData> {
  return {
    status: 'loading',
    data: previous?.data ?? null,
    error: null,
    errorMessage: null,
    lockMessage: null,
    isAuthError: false,
    isNotFound: false,
    isError: false,
  } satisfies MetricsState<TData>;
}

export function buildDemoLockedState<TData>(lockMessage: string = DEFAULT_DEMO_LOCK_MESSAGE): MetricsState<TData> {
  return {
    status: 'demo_locked',
    data: null,
    error: null,
    errorMessage: lockMessage,
    lockMessage,
    isAuthError: false,
    isNotFound: false,
    isError: false,
  } satisfies MetricsState<TData>;
}

export function buildReadyMetricsState<TData>(data: TData): MetricsState<TData> {
  return {
    status: 'ready',
    data,
    error: null,
    errorMessage: null,
    lockMessage: null,
    isAuthError: false,
    isNotFound: false,
    isError: false,
  } satisfies MetricsState<TData>;
}

export interface ErrorStateOptions {
  message?: string | null;
  isAuthError?: boolean;
  isNotFound?: boolean;
}

export function buildErrorMetricsState<TData>(
  error: Error | string,
  options?: ErrorStateOptions,
): MetricsState<TData> {
  const errorMessage = options?.message ?? deriveErrorMessage(error) ?? 'Unable to load metrics.';
  const isAuthError = options?.isAuthError ?? false;
  const isNotFound = options?.isNotFound ?? false;
  // isError is true for general errors (not auth or not found)
  const isError = !isAuthError && !isNotFound;
  
  return {
    status: 'error',
    data: null,
    error,
    errorMessage,
    lockMessage: null,
    isAuthError,
    isNotFound,
    isError,
  } satisfies MetricsState<TData>;
}

export function deriveErrorMessage(error: Error | string | null): string | null {
  if (!error) {
    return null;
  }
  return typeof error === 'string' ? error : error.message ?? null;
}
