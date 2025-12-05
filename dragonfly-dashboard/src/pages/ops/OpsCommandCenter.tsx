/**
 * OpsCommandCenter - Mission Control for Intake & System Health
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Three-pane high-density dashboard:
 *   1. Intake Station - Drag-and-drop CSV upload with progress
 *   2. Batch History - Recent uploads with status and error expansion
 *   3. System Pulse - Enrichment health + judgment counter
 *
 * Design: Mission Control aesthetic, dark mode compatible, high contrast
 */
import { type FC, useCallback, useMemo, useRef, useState } from 'react';
import {
  Upload,
  FileText,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Activity,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Database,
  Server,
  FileUp,
  Loader2,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/primitives';
import { Button } from '../../components/ui/Button';
import PageHeader from '../../components/ui/PageHeader';
import { EnrichmentHealth } from '../../components/ops/EnrichmentHealth';
import { useIntakeBatches, type IntakeBatch, type IntakeBatchStatus } from '../../hooks/useIntakeBatches';
import { useUploadIntake } from '../../hooks/useUploadIntake';
import { useRefreshBus } from '../../context/RefreshContext';
import { cn } from '../../lib/design-tokens';
import { formatDateTime } from '../../utils/formatters';

// ═══════════════════════════════════════════════════════════════════════════
// STATUS BADGE CONFIG
// ═══════════════════════════════════════════════════════════════════════════

interface StatusBadgeConfig {
  icon: typeof CheckCircle2;
  label: string;
  className: string;
}

const STATUS_CONFIG: Record<IntakeBatchStatus, StatusBadgeConfig> = {
  completed: {
    icon: CheckCircle2,
    label: 'Complete',
    className: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
  },
  failed: {
    icon: XCircle,
    label: 'Failed',
    className: 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/30',
  },
  processing: {
    icon: Loader2,
    label: 'Processing',
    className: 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/30',
  },
  pending: {
    icon: Clock,
    label: 'Pending',
    className: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30',
  },
};

// ═══════════════════════════════════════════════════════════════════════════
// STATUS BADGE COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const StatusBadge: FC<{ status: IntakeBatchStatus }> = ({ status }) => {
  const config = STATUS_CONFIG[status];
  const Icon = config.icon;
  const isAnimated = status === 'processing';

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border',
        config.className
      )}
    >
      <Icon className={cn('h-3 w-3', isAnimated && 'animate-spin')} />
      {config.label}
    </span>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// INTAKE STATION PANE
// ═══════════════════════════════════════════════════════════════════════════

interface IntakeStationProps {
  onUploadComplete: () => void;
  activeBatch: IntakeBatch | null;
  onViewErrors?: () => void;
}

const IntakeStation: FC<IntakeStationProps> = ({ onUploadComplete, activeBatch, onViewErrors }) => {
  const { state, uploadFile, reset } = useUploadIntake();
  const [isDragOver, setIsDragOver] = useState(false);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);

      const files = Array.from(e.dataTransfer.files);
      const csvFile = files.find((f) => f.name.toLowerCase().endsWith('.csv'));

      if (csvFile) {
        const result = await uploadFile(csvFile);
        if (result) {
          onUploadComplete();
        }
      }
    },
    [uploadFile, onUploadComplete]
  );

  const handleFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        const result = await uploadFile(file);
        if (result) {
          onUploadComplete();
        }
      }
      // Reset input
      e.target.value = '';
    },
    [uploadFile, onUploadComplete]
  );

  const isUploading = state.status === 'uploading' || state.status === 'processing';

  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base font-semibold">
          <Upload className="h-5 w-5 text-indigo-500" />
          Intake Station
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Drop Zone */}
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={cn(
            'relative flex flex-col items-center justify-center p-8 rounded-lg border-2 border-dashed transition-all duration-200',
            isDragOver
              ? 'border-indigo-500 bg-indigo-500/5'
              : 'border-slate-300 dark:border-slate-600 hover:border-indigo-400 hover:bg-slate-50 dark:hover:bg-slate-800/50',
            isUploading && 'pointer-events-none opacity-75'
          )}
        >
          {isUploading ? (
            <>
              <Loader2 className="h-12 w-12 text-indigo-500 animate-spin mb-3" />
              <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
                {state.status === 'uploading' ? 'Uploading...' : 'Processing...'}
              </p>
              <div className="w-full max-w-xs mt-4">
                <div className="h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-indigo-500 transition-all duration-300"
                    style={{ width: `${state.progress}%` }}
                  />
                </div>
                <p className="text-xs text-slate-500 mt-1 text-center">{state.progress}%</p>
              </div>
            </>
          ) : state.status === 'success' ? (
            <>
              <CheckCircle2 className="h-12 w-12 text-emerald-500 mb-3" />
              <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400">
                Upload Complete!
              </p>
              <p className="text-xs text-slate-500 mt-1">
                {state.result?.validRows} of {state.result?.totalRows} rows valid
              </p>
              <Button variant="ghost" size="sm" onClick={reset} className="mt-3">
                Upload Another
              </Button>
            </>
          ) : state.status === 'error' ? (
            <>
              <XCircle className="h-12 w-12 text-red-500 mb-3" />
              <p className="text-sm font-medium text-red-700 dark:text-red-400">Upload Failed</p>
              <p className="text-xs text-slate-500 mt-1 text-center max-w-xs">{state.error}</p>
              <div className="flex gap-2 mt-3">
                <Button variant="ghost" size="sm" onClick={reset}>
                  Try Again
                </Button>
                {state.errorCode === 'validation_error' && onViewErrors && (
                  <Button variant="secondary" size="sm" onClick={onViewErrors}>
                    View Errors
                  </Button>
                )}
              </div>
            </>
          ) : (
            <>
              <FileUp className="h-12 w-12 text-slate-400 mb-3" />
              <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
                Drop Simplicity CSV here
              </p>
              <p className="text-xs text-slate-500 mt-1">or click to browse</p>
              <input
                type="file"
                accept=".csv"
                onChange={handleFileSelect}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              />
            </>
          )}
        </div>

        {/* Active Batch Progress */}
        {activeBatch && (
          <div className="p-3 bg-blue-500/5 border border-blue-500/20 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
              <span className="text-sm font-medium text-blue-700 dark:text-blue-400">
                Processing Batch #{activeBatch.id.slice(0, 8)}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs text-slate-600 dark:text-slate-400">
              <span>{activeBatch.filename}</span>
              <span>
                {activeBatch.validRows}/{activeBatch.totalRows} rows
              </span>
            </div>
            <div className="mt-2 h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 transition-all duration-500"
                style={{
                  width: `${activeBatch.totalRows > 0 ? (activeBatch.validRows / activeBatch.totalRows) * 100 : 0}%`,
                }}
              />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// BATCH HISTORY PANE
// ═══════════════════════════════════════════════════════════════════════════

interface BatchHistoryProps {
  batches: IntakeBatch[];
  loading: boolean;
}

const BatchHistory: FC<BatchHistoryProps> = ({ batches, loading }) => {
  const [expandedBatchId, setExpandedBatchId] = useState<string | null>(null);

  const toggleExpand = useCallback((batchId: string) => {
    setExpandedBatchId((prev) => (prev === batchId ? null : batchId));
  }, []);

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="pb-3 flex-shrink-0">
        <CardTitle className="flex items-center gap-2 text-base font-semibold">
          <FileText className="h-5 w-5 text-indigo-500" />
          Batch History
          <span className="ml-auto text-xs font-normal text-slate-500">
            {batches.length} batches
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-auto">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-6 w-6 text-slate-400 animate-spin" />
          </div>
        ) : batches.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-slate-500">
            <Database className="h-8 w-8 mb-2 opacity-50" />
            <p className="text-sm">No batches yet</p>
          </div>
        ) : (
          <div className="space-y-2">
            {batches.map((batch) => (
              <BatchRow
                key={batch.id}
                batch={batch}
                isExpanded={expandedBatchId === batch.id}
                onToggle={() => toggleExpand(batch.id)}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// BATCH ROW COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

interface BatchRowProps {
  batch: IntakeBatch;
  isExpanded: boolean;
  onToggle: () => void;
}

const BatchRow: FC<BatchRowProps> = ({ batch, isExpanded, onToggle }) => {
  const hasErrors = batch.errorRows > 0 || (batch.recentErrors && batch.recentErrors.length > 0);
  const ChevronIcon = isExpanded ? ChevronUp : ChevronDown;

  return (
    <div
      className={cn(
        'rounded-lg border transition-all duration-200',
        batch.status === 'failed'
          ? 'border-red-500/30 bg-red-500/5'
          : batch.status === 'processing'
            ? 'border-blue-500/30 bg-blue-500/5'
            : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50'
      )}
    >
      <button
        onClick={onToggle}
        disabled={!hasErrors}
        className={cn(
          'w-full p-3 flex items-center gap-3 text-left',
          hasErrors && 'cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-700/50'
        )}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
              {batch.filename}
            </span>
            <StatusBadge status={batch.status} />
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            <span>{formatDateTime(batch.createdAt)}</span>
            <span>•</span>
            <span>
              {batch.validRows}/{batch.totalRows} rows
            </span>
            {batch.durationSeconds != null && (
              <>
                <span>•</span>
                <span>{batch.durationSeconds}s</span>
              </>
            )}
          </div>
        </div>
        {hasErrors && (
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-red-600 dark:text-red-400">
              {batch.errorRows} error{batch.errorRows !== 1 ? 's' : ''}
            </span>
            <ChevronIcon className="h-4 w-4 text-slate-400" />
          </div>
        )}
      </button>

      {/* Expanded Error Details */}
      {isExpanded && batch.recentErrors && batch.recentErrors.length > 0 && (
        <div className="px-3 pb-3 border-t border-slate-200 dark:border-slate-700">
          <div className="mt-3 space-y-2">
            {batch.recentErrors.map((error, idx) => (
              <div
                key={idx}
                className="flex items-start gap-2 p-2 bg-red-500/5 rounded text-xs"
              >
                <AlertTriangle className="h-3.5 w-3.5 text-red-500 mt-0.5 flex-shrink-0" />
                <div className="min-w-0">
                  <span className="font-medium text-red-700 dark:text-red-400">
                    Row {error.row}:
                  </span>{' '}
                  <span className="text-slate-600 dark:text-slate-400">{error.message}</span>
                  <span className="ml-1 text-slate-400">({error.code})</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// SYSTEM PULSE PANE
// ═══════════════════════════════════════════════════════════════════════════

interface SystemPulseProps {
  totalJudgments: number;
}

const SystemPulse: FC<SystemPulseProps> = ({ totalJudgments }) => {
  return (
    <div className="space-y-4">
      {/* Enrichment Health Widget */}
      <EnrichmentHealth />

      {/* Judgment Counter */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <Database className="h-4 w-4 text-indigo-500" />
            Judgments Ingested
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-slate-900 dark:text-slate-100">
              {totalJudgments.toLocaleString()}
            </span>
            <span className="text-sm text-slate-500">total</span>
          </div>
        </CardContent>
      </Card>

      {/* Quick System Status */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <Server className="h-4 w-4 text-indigo-500" />
            System Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <SystemStatusRow label="API" status="operational" />
            <SystemStatusRow label="Database" status="operational" />
            <SystemStatusRow label="Workers" status="operational" />
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

const SystemStatusRow: FC<{ label: string; status: 'operational' | 'degraded' | 'down' }> = ({
  label,
  status,
}) => {
  const statusConfig = {
    operational: { color: 'bg-emerald-500', text: 'Operational' },
    degraded: { color: 'bg-amber-500', text: 'Degraded' },
    down: { color: 'bg-red-500', text: 'Down' },
  };
  const config = statusConfig[status];

  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-sm text-slate-600 dark:text-slate-400">{label}</span>
      <div className="flex items-center gap-2">
        <span className={cn('h-2 w-2 rounded-full', config.color)} />
        <span className="text-xs text-slate-500">{config.text}</span>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// MAIN PAGE COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const OpsCommandCenter: FC = () => {
  const { triggerRefresh, isRefreshing } = useRefreshBus();
  const { state, batches, activeBatch, refetch, lastUpdated } = useIntakeBatches(20);
  const batchHistoryRef = useRef<HTMLDivElement>(null);

  const handleUploadComplete = useCallback(() => {
    // Refresh batch list after upload
    refetch();
  }, [refetch]);

  const handleViewErrors = useCallback(() => {
    // Scroll to batch history section
    batchHistoryRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  // Calculate total judgments from successful batches
  const totalJudgments = useMemo(() => {
    return batches
      .filter((b) => b.status === 'completed')
      .reduce((sum, b) => sum + b.validRows, 0);
  }, [batches]);

  const isLoading = state.status === 'loading' || state.status === 'idle';

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900">
      {/* Header */}
      <PageHeader
        title="Ops Command Center"
        description="Mission control for intake operations and system health"
        badge={<Activity className="h-5 w-5 text-indigo-500" />}
        actions={
          <Button
            variant="secondary"
            size="sm"
            onClick={triggerRefresh}
            disabled={isRefreshing}
            className="gap-2"
          >
            <RefreshCw className={cn('h-4 w-4', isRefreshing && 'animate-spin')} />
            Refresh
          </Button>
        }
      />

      {/* Last Updated */}
      {lastUpdated && (
        <div className="px-6 py-2 text-xs text-slate-500 dark:text-slate-400">
          Last updated: {formatDateTime(lastUpdated.toISOString())}
        </div>
      )}

      {/* Three-Pane Layout */}
      <div className="p-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Pane 1: Intake Station */}
        <div className="lg:col-span-1">
          <IntakeStation
            onUploadComplete={handleUploadComplete}
            activeBatch={activeBatch}
            onViewErrors={handleViewErrors}
          />
        </div>

        {/* Pane 2: Batch History */}
        <div className="lg:col-span-1" ref={batchHistoryRef}>
          <BatchHistory batches={batches} loading={isLoading} />
        </div>

        {/* Pane 3: System Pulse */}
        <div className="lg:col-span-1">
          <SystemPulse totalJudgments={totalJudgments} />
        </div>
      </div>
    </div>
  );
};

export default OpsCommandCenter;
