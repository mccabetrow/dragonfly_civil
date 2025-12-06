/**
 * ApiErrorBanner
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Reusable banner component for displaying API-related errors with contextual
 * guidance. Differentiates between auth errors, network/CORS errors, and
 * general API failures.
 *
 * Usage:
 *   <ApiErrorBanner
 *     isAuthError={state.isAuthError}
 *     isNetworkError={state.isError && !state.isNotFound}
 *     onRetry={refetch}
 *   />
 */
import React from 'react';
import { AlertTriangle, KeyRound, Wifi, WifiOff } from 'lucide-react';
import { cn } from '../lib/design-tokens';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface ApiErrorBannerProps {
  /** True if this is an authentication error (401/403) */
  isAuthError?: boolean;
  /** True if this is a network/CORS error */
  isNetworkError?: boolean;
  /** Custom error message (overrides defaults) */
  message?: string;
  /** Retry callback */
  onRetry?: () => void | Promise<void>;
  /** Additional CSS classes */
  className?: string;
  /** Whether retry is currently in progress */
  isRetrying?: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const ApiErrorBanner: React.FC<ApiErrorBannerProps> = ({
  isAuthError = false,
  isNetworkError = false,
  message,
  onRetry,
  className,
  isRetrying = false,
}) => {
  // Determine banner content based on error type
  let Icon = AlertTriangle;
  let title = 'Something went wrong';
  let description = message ?? 'Unable to load data. Please try again.';
  let bgColor = 'bg-rose-50/80 border-rose-200/80';
  let textColor = 'text-rose-800';
  let iconBg = 'bg-rose-100 text-rose-600';

  if (isAuthError) {
    Icon = KeyRound;
    title = 'API Key Configuration Issue';
    description =
      message ??
      'Check that VITE_DRAGONFLY_API_KEY in Vercel matches DRAGONFLY_API_KEY in Railway.';
    bgColor = 'bg-amber-50/80 border-amber-200/80';
    textColor = 'text-amber-800';
    iconBg = 'bg-amber-100 text-amber-600';
  } else if (isNetworkError) {
    Icon = WifiOff;
    title = 'Unable to Reach Backend';
    description =
      message ??
      'Check the System Diagnostic badge in the sidebar for connection status. Verify Railway deployment is running.';
    bgColor = 'bg-slate-100/80 border-slate-300/80';
    textColor = 'text-slate-700';
    iconBg = 'bg-slate-200 text-slate-600';
  }

  return (
    <div
      className={cn(
        'rounded-2xl border p-4 shadow-sm',
        bgColor,
        textColor,
        className
      )}
      role="alert"
    >
      <div className="flex items-start gap-3">
        <span className={cn('rounded-xl p-2 flex-shrink-0', iconBg)}>
          <Icon className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="flex-1 space-y-2">
          <div>
            <p className="text-sm font-semibold">{title}</p>
            <p className="text-sm leading-relaxed opacity-90">{description}</p>
          </div>
          {onRetry && (
            <button
              type="button"
              onClick={() => onRetry()}
              disabled={isRetrying}
              className={cn(
                'inline-flex items-center gap-2 rounded-full border bg-white/80 px-3 py-1.5',
                'text-xs font-semibold uppercase tracking-wide transition',
                'hover:bg-white focus-visible:outline focus-visible:outline-2',
                isAuthError
                  ? 'border-amber-200 text-amber-700 focus-visible:outline-amber-400'
                  : isNetworkError
                    ? 'border-slate-300 text-slate-600 focus-visible:outline-slate-400'
                    : 'border-rose-200 text-rose-700 focus-visible:outline-rose-400',
                isRetrying && 'cursor-not-allowed opacity-60'
              )}
            >
              {isRetrying ? (
                <>
                  <span
                    className="inline-flex h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
                    aria-hidden="true"
                  />
                  Retrying…
                </>
              ) : (
                <>
                  <Wifi className="h-3 w-3" aria-hidden="true" />
                  Retry
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default ApiErrorBanner;
