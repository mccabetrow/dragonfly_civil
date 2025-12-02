import React from 'react';
import DemoLockCard from './DemoLockCard';
import { DashboardError } from './DashboardError';
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

  if (state.status === 'error') {
    const message = state.errorMessage ?? 'We could not load this data.';
    return (
      <DashboardError
        className={className}
        title={errorTitle}
        message={message}
        onRetry={onRetry}
      />
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
