/**
 * EnrichmentHealth
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Widget showing enrichment worker health status.
 * Displays queue depth, processing status, and failure alerts.
 */
import React from 'react';
import { Activity, AlertTriangle, CheckCircle2, Clock, Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../primitives';
import { useEnrichmentHealth } from '../../hooks/useEnrichmentHealth';
import { cn } from '../../lib/design-tokens';

interface EnrichmentHealthProps {
  className?: string;
}

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
          <div className="h-16 bg-muted rounded" />
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

  const StatusIcon = data.isHealthy ? CheckCircle2 : AlertTriangle;
  const statusColor = data.isHealthy ? 'text-green-500' : 'text-amber-500';
  const statusBg = data.isHealthy ? 'bg-green-500/10' : 'bg-amber-500/10';

  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-muted-foreground" />
            Enrichment Worker
          </span>
          <span
            className={cn(
              'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
              statusBg,
              statusColor
            )}
          >
            <StatusIcon className="h-3 w-3" />
            {data.isHealthy ? 'Healthy' : 'Degraded'}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-4 gap-3 text-center">
          {/* Queued */}
          <div className="space-y-1">
            <div className="flex items-center justify-center">
              <Clock className="h-4 w-4 text-blue-500" />
            </div>
            <p className="text-lg font-semibold tabular-nums">{data.queuedCount}</p>
            <p className="text-xs text-muted-foreground">Queued</p>
          </div>

          {/* Processing */}
          <div className="space-y-1">
            <div className="flex items-center justify-center">
              <Loader2 className={cn('h-4 w-4 text-indigo-500', data.processingCount > 0 && 'animate-spin')} />
            </div>
            <p className="text-lg font-semibold tabular-nums">{data.processingCount}</p>
            <p className="text-xs text-muted-foreground">Processing</p>
          </div>

          {/* Completed */}
          <div className="space-y-1">
            <div className="flex items-center justify-center">
              <CheckCircle2 className="h-4 w-4 text-green-500" />
            </div>
            <p className="text-lg font-semibold tabular-nums">{data.completedCount}</p>
            <p className="text-xs text-muted-foreground">Done</p>
          </div>

          {/* Failed */}
          <div className="space-y-1">
            <div className="flex items-center justify-center">
              <AlertTriangle className={cn('h-4 w-4', data.failedCount > 0 ? 'text-red-500' : 'text-muted-foreground')} />
            </div>
            <p className={cn('text-lg font-semibold tabular-nums', data.failedCount > 0 && 'text-red-500')}>
              {data.failedCount}
            </p>
            <p className="text-xs text-muted-foreground">Failed</p>
          </div>
        </div>

        {/* Last processed timestamp */}
        {data.lastProcessed && (
          <p className="mt-3 text-xs text-muted-foreground text-center border-t pt-2">
            Last completed: {formatTimestamp(data.lastProcessed)}
          </p>
        )}
      </CardContent>
    </Card>
  );
};

function formatTimestamp(iso: string): string {
  try {
    const date = new Date(iso);
    return date.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export default EnrichmentHealth;
