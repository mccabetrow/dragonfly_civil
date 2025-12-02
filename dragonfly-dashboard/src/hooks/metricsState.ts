export type MetricsStatus = 'idle' | 'loading' | 'ready' | 'demo_locked' | 'error';

export interface MetricsSnapshot<TData> {
  status: MetricsStatus;
  data: TData | null;
  error: Error | string | null;
  errorMessage: string | null;
  lockMessage?: string | null;
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
  } satisfies MetricsState<TData>;
}

export function buildLoadingMetricsState<TData>(previous?: MetricsState<TData>): MetricsState<TData> {
  return {
    status: 'loading',
    data: previous?.data ?? null,
    error: null,
    errorMessage: null,
    lockMessage: null,
  } satisfies MetricsState<TData>;
}

export function buildDemoLockedState<TData>(lockMessage: string = DEFAULT_DEMO_LOCK_MESSAGE): MetricsState<TData> {
  return {
    status: 'demo_locked',
    data: null,
    error: null,
    errorMessage: lockMessage,
    lockMessage,
  } satisfies MetricsState<TData>;
}

export function buildReadyMetricsState<TData>(data: TData): MetricsState<TData> {
  return {
    status: 'ready',
    data,
    error: null,
    errorMessage: null,
    lockMessage: null,
  } satisfies MetricsState<TData>;
}

export function buildErrorMetricsState<TData>(
  error: Error | string,
  options?: { message?: string | null },
): MetricsState<TData> {
  const errorMessage = options?.message ?? deriveErrorMessage(error) ?? 'Unable to load metrics.';
  return {
    status: 'error',
    data: null,
    error,
    errorMessage,
    lockMessage: null,
  } satisfies MetricsState<TData>;
}

export function deriveErrorMessage(error: Error | string | null): string | null {
  if (!error) {
    return null;
  }
  return typeof error === 'string' ? error : error.message ?? null;
}
