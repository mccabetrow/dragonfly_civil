/**
 * OpsAlertsPanel - Exception alerts and notifications for ops
 * 
 * Shows items that need immediate attention.
 */
import type { FC } from 'react';
import { AlertTriangle, Bell, CheckCircle, Clock, X, ChevronRight } from 'lucide-react';
import { cn } from '../../lib/design-tokens';

export interface OpsAlert {
  id: string;
  type: 'warning' | 'error' | 'info' | 'success';
  title: string;
  message: string;
  timestamp: string;
  actionLabel?: string;
  onAction?: () => void;
  dismissible?: boolean;
}

interface OpsAlertsPanelProps {
  /** Alert items to display */
  alerts: OpsAlert[];
  /** Called when an alert is dismissed */
  onDismiss?: (alertId: string) => void;
  /** Whether data is loading */
  isLoading?: boolean;
  /** Additional className */
  className?: string;
}

const ALERT_STYLES: Record<OpsAlert['type'], { bg: string; icon: typeof AlertTriangle; iconColor: string }> = {
  warning: {
    bg: 'bg-amber-50 border-amber-200',
    icon: AlertTriangle,
    iconColor: 'text-amber-500',
  },
  error: {
    bg: 'bg-red-50 border-red-200',
    icon: AlertTriangle,
    iconColor: 'text-red-500',
  },
  info: {
    bg: 'bg-blue-50 border-blue-200',
    icon: Bell,
    iconColor: 'text-blue-500',
  },
  success: {
    bg: 'bg-emerald-50 border-emerald-200',
    icon: CheckCircle,
    iconColor: 'text-emerald-500',
  },
};

const OpsAlertsPanel: FC<OpsAlertsPanelProps> = ({
  alerts,
  onDismiss,
  isLoading,
  className,
}) => {
  if (isLoading) {
    return (
      <div className={cn('rounded-2xl border border-slate-200 bg-white p-6 shadow-sm', className)}>
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-50">
            <Bell className="h-5 w-5 text-amber-600" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Alerts</h3>
            <p className="text-xs text-slate-500">Loading...</p>
          </div>
        </div>
        <div className="space-y-3">
          {[1, 2].map((i) => (
            <div key={i} className="animate-pulse rounded-xl bg-slate-100 h-16" />
          ))}
        </div>
      </div>
    );
  }

  if (alerts.length === 0) {
    return (
      <div className={cn('rounded-2xl border border-slate-200 bg-white p-6 shadow-sm', className)}>
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100">
            <Bell className="h-5 w-5 text-slate-400" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Alerts</h3>
            <p className="text-xs text-slate-500">All clear</p>
          </div>
        </div>
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/50 p-6 text-center">
          <CheckCircle className="mx-auto h-8 w-8 text-emerald-400" />
          <p className="mt-2 text-sm font-medium text-slate-600">No alerts right now</p>
          <p className="mt-1 text-xs text-slate-400">Issues that need attention will appear here</p>
        </div>
      </div>
    );
  }

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    
    if (diffHours < 1) {
      const diffMins = Math.floor(diffMs / (1000 * 60));
      return `${diffMins}m ago`;
    }
    if (diffHours < 24) {
      return `${diffHours}h ago`;
    }
    return date.toLocaleDateString();
  };

  // Count by type
  const errorCount = alerts.filter(a => a.type === 'error').length;
  const warningCount = alerts.filter(a => a.type === 'warning').length;

  return (
    <div className={cn('rounded-2xl border border-slate-200 bg-white shadow-sm', className)}>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className={cn(
            'flex h-10 w-10 items-center justify-center rounded-xl',
            errorCount > 0 ? 'bg-red-50' : warningCount > 0 ? 'bg-amber-50' : 'bg-slate-100'
          )}>
            <Bell className={cn(
              'h-5 w-5',
              errorCount > 0 ? 'text-red-600' : warningCount > 0 ? 'text-amber-600' : 'text-slate-400'
            )} />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Alerts</h3>
            <p className="text-xs text-slate-500">{alerts.length} item{alerts.length !== 1 ? 's' : ''} need attention</p>
          </div>
        </div>
        {(errorCount > 0 || warningCount > 0) && (
          <div className="flex items-center gap-2">
            {errorCount > 0 && (
              <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-semibold text-red-700">
                {errorCount} error{errorCount !== 1 ? 's' : ''}
              </span>
            )}
            {warningCount > 0 && (
              <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-700">
                {warningCount} warning{warningCount !== 1 ? 's' : ''}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Alerts list */}
      <div className="divide-y divide-slate-100 max-h-[300px] overflow-y-auto">
        {alerts.map((alert) => {
          const style = ALERT_STYLES[alert.type];
          const Icon = style.icon;
          
          return (
            <div
              key={alert.id}
              className={cn(
                'relative px-6 py-4',
                style.bg,
                'border-l-4',
                alert.type === 'error' && 'border-l-red-500',
                alert.type === 'warning' && 'border-l-amber-500',
                alert.type === 'info' && 'border-l-blue-500',
                alert.type === 'success' && 'border-l-emerald-500'
              )}
            >
              <div className="flex items-start gap-3">
                <Icon className={cn('h-5 w-5 shrink-0 mt-0.5', style.iconColor)} />
                
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <h4 className="font-medium text-slate-900 text-sm">{alert.title}</h4>
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-slate-400 flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {formatTimestamp(alert.timestamp)}
                      </span>
                      {alert.dismissible && onDismiss && (
                        <button
                          type="button"
                          onClick={() => onDismiss(alert.id)}
                          className="rounded p-1 text-slate-400 hover:bg-white/50 hover:text-slate-600"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </div>
                  <p className="mt-1 text-sm text-slate-600">{alert.message}</p>
                  {alert.actionLabel && alert.onAction && (
                    <button
                      type="button"
                      onClick={alert.onAction}
                      className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-blue-600 hover:text-blue-700"
                    >
                      {alert.actionLabel}
                      <ChevronRight className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default OpsAlertsPanel;
