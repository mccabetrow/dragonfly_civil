/**
 * EnrichmentHealth
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Widget showing enrichment worker health status.
 * Displays queue depth, processing status, and failure alerts.
 *
 * Status logic:
 * - Red "System Degraded" if failed_jobs > 0
 * - Yellow "Backlog High" if pending_jobs > 100
 * - Gray "Idle" if pending_jobs = 0 and processing_jobs = 0
 * - Green "Enrichment Active" otherwise
 */
import React from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Loader2,
  ExternalLink,
  XCircle,
  Pause,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../primitives';
import {
  useEnrichmentHealth,
  humanizeInterval,
  type EnrichmentStatus,
} from '../../hooks/useEnrichmentHealth';
import { cn } from '../../lib/design-tokens';

interface EnrichmentHealthProps {
  className?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// STATUS CONFIG
// ═══════════════════════════════════════════════════════════════════════════

interface StatusConfig {
  icon: React.ElementType;
  label: string;
  bgClass: string;
  textClass: string;
  borderClass: string;
}

const STATUS_CONFIG: Record<EnrichmentStatus, StatusConfig> = {
  degraded: {
    icon: XCircle,
    label: 'System Degraded',
    bgClass: 'bg-red-500/10',
    textClass: 'text-red-600 dark:text-red-400',
    borderClass: 'border-red-500/30',
  },
  backlog: {
    icon: AlertTriangle,
    label: 'Backlog High',
    bgClass: 'bg-amber-500/10',
    textClass: 'text-amber-600 dark:text-amber-400',
    borderClass: 'border-amber-500/30',
  },
  idle: {
    icon: Pause,
    label: 'Idle',
    bgClass: 'bg-gray-500/10',
    textClass: 'text-gray-600 dark:text-gray-400',
    borderClass: 'border-gray-500/30',
  },
  active: {
    icon: CheckCircle2,
    label: 'Enrichment Active',
    bgClass: 'bg-green-500/10',
    textClass: 'text-green-600 dark:text-green-400',
    borderClass: 'border-green-500/30',
  },
};

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const EnrichmentHealth: React.FC<EnrichmentHealthProps> = ({ className }) => {
  const { state } = useEnrichmentHealth();

  if (state.status === 'loading' || state.status === 'idle') {
    return (
      <Card className={cn('animate-pulse', className)}>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Activity className="h-4 w-4 text-muted-foreground" />
            Enrichment Worker
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-20 bg-muted rounded" />
        </CardContent>
      </Card>
    );
  }

  if (state.status === 'error') {
    return (
      <Card className={cn('border-destructive/50', className)}>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-destructive" />
            Enrichment Worker
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{state.errorMessage}</p>
        </CardContent>
      </Card>
    );
  }

  if (state.status === 'demo_locked') {
    return (
      <Card className={cn('opacity-75', className)}>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Activity className="h-4 w-4 text-muted-foreground" />
            Enrichment Worker
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Demo mode — metrics hidden</p>
        </CardContent>
      </Card>
    );
  }

  const data = state.data;
  if (!data) return null;

  const config = STATUS_CONFIG[data.status];
  const StatusIcon = config.icon;

  return (
    <Card className={cn(config.borderClass, className)}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-muted-foreground" />
            Enrichment Worker
          </span>
          <span
            className={cn(
              'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
              config.bgClass,
              config.textClass
            )}
          >
            <StatusIcon className="h-3 w-3" />
            {config.label}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-4 gap-3 text-center">
          {/* Pending */}
          <div className="space-y-1">
            <div className="flex items-center justify-center">
              <Clock className={cn('h-4 w-4', data.pendingJobs > 100 ? 'text-amber-500' : 'text-blue-500')} />
            </div>
            <p className={cn('text-lg font-semibold tabular-nums', data.pendingJobs > 100 && 'text-amber-500')}>
              {data.pendingJobs}
            </p>
            <p className="text-xs text-muted-foreground">Pending</p>
          </div>

          {/* Processing */}
          <div className="space-y-1">
            <div className="flex items-center justify-center">
              <Loader2
                className={cn(
                  'h-4 w-4 text-indigo-500',
                  data.processingJobs > 0 && 'animate-spin'
                )}
              />
            </div>
            <p className="text-lg font-semibold tabular-nums">{data.processingJobs}</p>
            <p className="text-xs text-muted-foreground">Processing</p>
          </div>

          {/* Completed */}
          <div className="space-y-1">
            <div className="flex items-center justify-center">
              <CheckCircle2 className="h-4 w-4 text-green-500" />
            </div>
            <p className="text-lg font-semibold tabular-nums">{data.completedJobs}</p>
            <p className="text-xs text-muted-foreground">Completed</p>
          </div>

          {/* Failed */}
          <div className="space-y-1">
            <div className="flex items-center justify-center">
              <XCircle
                className={cn('h-4 w-4', data.failedJobs > 0 ? 'text-red-500' : 'text-muted-foreground')}
              />
            </div>
            <p className={cn('text-lg font-semibold tabular-nums', data.failedJobs > 0 && 'text-red-500')}>
              {data.failedJobs}
            </p>
            <p className="text-xs text-muted-foreground">Failed</p>
          </div>
        </div>

        {/* Footer: Last activity + View queue link */}
        <div className="mt-3 pt-2 border-t flex items-center justify-between text-xs">
          <span className="text-muted-foreground">
            Last activity: {humanizeInterval(data.timeSinceLastActivity)}
          </span>
          <Link
            to="/ops/queue"
            className="inline-flex items-center gap-1 text-primary hover:underline"
          >
            View queue
            <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
      </CardContent>
    </Card>
  );
};

export default EnrichmentHealth;
