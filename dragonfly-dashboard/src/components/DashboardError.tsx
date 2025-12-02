import React from 'react';
import { AlertTriangle } from 'lucide-react';

export interface DashboardErrorProps {
  message: string;
  onRetry?: () => void | Promise<void>;
  title?: string;
  className?: string;
  helperText?: string;
  isRetrying?: boolean;
  disableRetry?: boolean;
}

export const DashboardError: React.FC<DashboardErrorProps> = ({
  message,
  onRetry,
  title = "We couldn't load this data.",
  className = '',
  helperText,
  isRetrying = false,
  disableRetry = false,
}) => (
  <div
    className={[
      'rounded-2xl border border-rose-200/80 bg-rose-50/80 p-5 text-sm text-rose-800 shadow-sm shadow-rose-200/40',
      className,
    ].join(' ')}
  >
    <div className="flex items-start gap-3">
      <span className="rounded-2xl bg-rose-100 p-2 text-rose-600">
        <AlertTriangle className="h-5 w-5" aria-hidden="true" />
      </span>
      <div className="space-y-2">
        <div>
          <p className="text-sm font-semibold text-rose-900">{title}</p>
          <p className="text-sm leading-relaxed text-rose-700">{message}</p>
          {helperText ? (
            <p className="mt-2 text-xs font-medium uppercase tracking-wide text-rose-600">
              {helperText}
            </p>
          ) : null}
        </div>
        {onRetry ? (
          <button
            type="button"
            onClick={() => onRetry()}
            disabled={disableRetry || isRetrying}
            className={`inline-flex w-fit items-center gap-2 rounded-full border border-rose-200 bg-white/80 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-rose-700 transition hover:bg-rose-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-rose-400 ${
              disableRetry || isRetrying ? 'cursor-not-allowed opacity-60' : ''
            }`}
          >
            {isRetrying ? (
              <>
                <span className="inline-flex h-3 w-3 animate-spin rounded-full border-2 border-rose-300 border-t-transparent" aria-hidden="true" />
                Retrying…
              </>
            ) : (
              'Retry'
            )}
          </button>
        ) : null}
      </div>
    </div>
  </div>
);
