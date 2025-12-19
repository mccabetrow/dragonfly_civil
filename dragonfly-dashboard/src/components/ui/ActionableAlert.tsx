/**
 * ActionableAlert - Enterprise-grade error/warning display with specific diagnostics
 *
 * Replaces generic "Unable to load" with actionable instructions:
 * - 502/Network: "API Unreachable. Check System Status."
 * - 401/403: "Unauthorized. Verify Vercel API Key."
 * - 404/Empty: "No Data Found. Enrichment may be pending."
 */

import { type FC, type ReactNode } from 'react';
import { AlertTriangle, Info, RefreshCw, XCircle } from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import type { ErrorSeverity } from '../../utils/dashboardErrors';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface ActionableAlertProps {
  /** Main error/warning message (e.g., "API Unreachable") */
  title: string;
  /** Actionable hint for the user (e.g., "Check System Status") */
  actionHint?: string;
  /** Severity determines color scheme */
  severity?: ErrorSeverity;
  /** Error code for debugging (e.g., "502", "PGRST116") */
  code?: string | null;
  /** Retry callback */
  onRetry?: () => void | Promise<void>;
  /** Whether retry is in progress */
  isRetrying?: boolean;
  /** Additional content below the message */
  children?: ReactNode;
  /** Compact mode for inline use */
  compact?: boolean;
  /** Additional CSS classes */
  className?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// STYLE CONFIG
// ═══════════════════════════════════════════════════════════════════════════

const severityConfig: Record<
  ErrorSeverity,
  {
    containerClass: string;
    iconBgClass: string;
    iconColorClass: string;
    titleClass: string;
    textClass: string;
    buttonClass: string;
    Icon: typeof AlertTriangle;
  }
> = {
  error: {
    containerClass: 'border-rose-200/80 bg-rose-50/80 shadow-rose-200/40',
    iconBgClass: 'bg-rose-100',
    iconColorClass: 'text-rose-600',
    titleClass: 'text-rose-900',
    textClass: 'text-rose-700',
    buttonClass: 'border-rose-200 text-rose-700 hover:bg-rose-100 focus-visible:outline-rose-400',
    Icon: XCircle,
  },
  warning: {
    containerClass: 'border-amber-200/80 bg-amber-50/80 shadow-amber-200/40',
    iconBgClass: 'bg-amber-100',
    iconColorClass: 'text-amber-600',
    titleClass: 'text-amber-900',
    textClass: 'text-amber-700',
    buttonClass: 'border-amber-200 text-amber-700 hover:bg-amber-100 focus-visible:outline-amber-400',
    Icon: AlertTriangle,
  },
  info: {
    containerClass: 'border-sky-200/80 bg-sky-50/80 shadow-sky-200/40',
    iconBgClass: 'bg-sky-100',
    iconColorClass: 'text-sky-600',
    titleClass: 'text-sky-900',
    textClass: 'text-sky-700',
    buttonClass: 'border-sky-200 text-sky-700 hover:bg-sky-100 focus-visible:outline-sky-400',
    Icon: Info,
  },
};

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const ActionableAlert: FC<ActionableAlertProps> = ({
  title,
  actionHint,
  severity = 'error',
  code,
  onRetry,
  isRetrying = false,
  children,
  compact = false,
  className,
}) => {
  const config = severityConfig[severity];
  const { Icon } = config;

  if (compact) {
    return (
      <div
        className={cn(
          'flex items-center gap-2 rounded-lg border px-3 py-2 text-xs',
          config.containerClass,
          className
        )}
      >
        <Icon className={cn('h-4 w-4 flex-shrink-0', config.iconColorClass)} aria-hidden="true" />
        <span className={cn('font-medium', config.titleClass)}>{title}</span>
        {actionHint && (
          <span className={cn('hidden sm:inline', config.textClass)}>— {actionHint}</span>
        )}
        {code && (
          <code className="ml-auto rounded bg-white/50 px-1.5 py-0.5 font-mono text-[10px] opacity-60">
            {code}
          </code>
        )}
      </div>
    );
  }

  return (
    <div
      className={cn(
        'rounded-2xl border p-5 text-sm shadow-sm',
        config.containerClass,
        className
      )}
    >
      <div className="flex items-start gap-3">
        <span className={cn('rounded-2xl p-2', config.iconBgClass, config.iconColorClass)}>
          <Icon className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="flex-1 space-y-2">
          <div>
            <div className="flex items-center gap-2">
              <p className={cn('text-sm font-semibold', config.titleClass)}>{title}</p>
              {code && (
                <code className="rounded bg-white/50 px-1.5 py-0.5 font-mono text-[10px] opacity-60">
                  {code}
                </code>
              )}
            </div>
            {actionHint && (
              <p className={cn('mt-1 text-sm leading-relaxed', config.textClass)}>{actionHint}</p>
            )}
          </div>
          {children}
          {onRetry && (
            <button
              type="button"
              onClick={() => onRetry()}
              disabled={isRetrying}
              className={cn(
                'inline-flex w-fit items-center gap-2 rounded-full border bg-white/80 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide transition focus-visible:outline focus-visible:outline-2',
                config.buttonClass,
                isRetrying && 'cursor-not-allowed opacity-60'
              )}
            >
              {isRetrying ? (
                <>
                  <RefreshCw className="h-3 w-3 animate-spin" aria-hidden="true" />
                  Retrying…
                </>
              ) : (
                <>
                  <RefreshCw className="h-3 w-3" aria-hidden="true" />
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

export default ActionableAlert;
