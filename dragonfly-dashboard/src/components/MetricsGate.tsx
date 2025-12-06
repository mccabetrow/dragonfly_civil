import React from 'react';
import DemoLockCard from './DemoLockCard';
import StatusMessage from './StatusMessage';
import { DEFAULT_DEMO_LOCK_MESSAGE, type MetricsState } from '../hooks/metricsState';

interface MetricsGateProps<TData> {
  state: MetricsState<TData>;
  loadingFallback?: React.ReactNode;
  ready: React.ReactNode;
  errorTitle?: string;
  onRetry?: () => void | Promise<void>;
  lockMessage?: string;
  className?: string;
  showReadyWhileLoading?: boolean;
  refreshingMessage?: string;
}

/**
 * Subtle skeleton placeholder for unavailable data.
 * Shows a calm "Data Pending" state rather than a red error banner.
 */
function DataPendingSkeleton({
  title,
  onRetry,
  className = '',
}: {
  title?: string;
  onRetry?: () => void | Promise<void>;
  className?: string;
}) {
  return (
    <div
      className={[
        'rounded-2xl border border-slate-200 bg-slate-50/60 p-5 text-sm text-slate-500 animate-pulse',
        className,
      ].join(' ')}
    >
      <div className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-full bg-slate-200" />
        <div className="flex-1 space-y-2">
          <div className="h-4 w-1/3 rounded bg-slate-200" />
          <div className="h-3 w-2/3 rounded bg-slate-200" />
        </div>
      </div>
      <div className="mt-4 flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
          {title ?? 'Data pending'}
        </p>
        {onRetry && (
          <button
            type="button"
            onClick={() => onRetry()}
            className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition hover:bg-slate-100"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

function MetricsGate<TData>({
  state,
  loadingFallback,
  ready,
  errorTitle,
  onRetry,
  lockMessage,
  className = '',
  showReadyWhileLoading = false,
  refreshingMessage = 'Refreshing data…',
}: MetricsGateProps<TData>) {
  if (state.status === 'demo_locked') {
    return (
      <div className={className}>
        <DemoLockCard description={state.lockMessage ?? lockMessage ?? DEFAULT_DEMO_LOCK_MESSAGE} />
      </div>
    );
  }

  // Show subtle skeleton for all error states (404, 500, network, auth)
  // instead of massive red banners
  if (state.status === 'error') {
    return (
      <div className={className}>
        <DataPendingSkeleton title={errorTitle} onRetry={onRetry} />
      </div>
    );
  }

  if (state.status === 'loading' || state.status === 'idle') {
    if (showReadyWhileLoading && state.data) {
      return (
        <div className={className}>
          {loadingFallback ?? <StatusMessage tone="info">{refreshingMessage}</StatusMessage>}
          {ready}
        </div>
      );
    }
    return (
      <div className={className}>
        {loadingFallback ?? <StatusMessage tone="info">Loading data…</StatusMessage>}
      </div>
    );
  }

  if (state.status !== 'ready') {
    return null;
  }

  return <div className={className}>{ready}</div>;
}

export default MetricsGate;
