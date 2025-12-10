/**
 * IntakeStationPage - Dedicated Intake Management Dashboard
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Mission Control for judgment intake operations:
 *   - Real-time intake radar metrics (24h/7d judgment counts, AUM, validity)
 *   - Drag-and-drop CSV upload with progress tracking
 *   - Batch history with expandable error details
 *   - Processing queue status
 *
 * Design:
 *   - Skeleton loaders (no spinners) for graceful loading states
 *   - Auto-refresh every 30s when active
 *   - RefreshContext integration for manual refresh
 *   - Dark mode compatible, high-contrast UI
 *
 * Route: /intake
 */
import { type FC, useCallback, useMemo, useRef, useState } from 'react';
import {
  Upload,
  FileText,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Database,
  FileUp,
  Loader2,
  TrendingUp,
  DollarSign,
  Activity,
  AlertCircle,
  Zap,
  BarChart3,
} from 'lucide-react';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '../components/primitives';
import { Button } from '../components/ui/Button';
import PageHeader from '../components/ui/PageHeader';
import { useIntakeStationData, type IntakeBatchSummary } from '../hooks/useIntakeStationData';
import { useUploadIntake } from '../hooks/useUploadIntake';
import { useRefreshBus } from '../context/RefreshContext';
import { cn } from '../lib/design-tokens';
import { telemetry } from '../utils/logUiAction';

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function formatCurrency(value: number): string {
  if (value >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `$${(value / 1_000).toFixed(0)}K`;
  }
  return `$${value.toFixed(0)}`;
}

function formatDateTime(isoString: string | null): string {
  if (!isoString) return '—';
  const date = new Date(isoString);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs}s`;
}

// ═══════════════════════════════════════════════════════════════════════════
// SKELETON COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

const MetricCardSkeleton: FC = () => (
  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm animate-pulse">
    <div className="h-3 w-24 bg-slate-200 rounded mb-3" />
    <div className="h-8 w-16 bg-slate-200 rounded" />
  </div>
);

const BatchRowSkeleton: FC = () => (
  <div className="p-4 border border-slate-200 rounded-lg animate-pulse">
    <div className="flex items-center gap-3">
      <div className="h-4 w-32 bg-slate-200 rounded" />
      <div className="h-5 w-20 bg-slate-200 rounded-full" />
      <div className="flex-1" />
      <div className="h-4 w-24 bg-slate-200 rounded" />
    </div>
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// STATUS BADGE
// ═══════════════════════════════════════════════════════════════════════════

type BatchStatus = 'pending' | 'processing' | 'completed' | 'failed';

interface StatusBadgeConfig {
  icon: typeof CheckCircle2;
  label: string;
  className: string;
}

const STATUS_CONFIG: Record<BatchStatus, StatusBadgeConfig> = {
  completed: {
    icon: CheckCircle2,
    label: 'Complete',
    className: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/30',
  },
  failed: {
    icon: XCircle,
    label: 'Failed',
    className: 'bg-red-500/10 text-red-600 border-red-500/30',
  },
  processing: {
    icon: Loader2,
    label: 'Processing',
    className: 'bg-blue-500/10 text-blue-600 border-blue-500/30',
  },
  pending: {
    icon: Clock,
    label: 'Pending',
    className: 'bg-amber-500/10 text-amber-600 border-amber-500/30',
  },
};

const StatusBadge: FC<{ status: BatchStatus }> = ({ status }) => {
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
// METRIC CARD
// ═══════════════════════════════════════════════════════════════════════════

interface MetricCardProps {
  icon: typeof TrendingUp;
  iconColor: string;
  label: string;
  value: string | number;
  valueColor?: string;
  subtext?: string;
}

const MetricCard: FC<MetricCardProps> = ({
  icon: Icon,
  iconColor,
  label,
  value,
  valueColor = 'text-slate-900',
  subtext,
}) => (
  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
    <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
      <Icon className={cn('h-3.5 w-3.5', iconColor)} />
      {label}
    </div>
    <div className={cn('text-2xl font-bold', valueColor)}>{value}</div>
    {subtext && <div className="text-xs text-slate-400 mt-1">{subtext}</div>}
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// UPLOAD ZONE
// ═══════════════════════════════════════════════════════════════════════════

interface UploadZoneProps {
  onUploadComplete: () => void;
}

const UploadZone: FC<UploadZoneProps> = ({ onUploadComplete }) => {
  const { state, uploadFile, reset } = useUploadIntake();
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

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
          // Log telemetry for successful upload
          telemetry.intakeUploadSubmitted({
            batchId: result.batchId,
            filename: result.filename,
            rowCount: result.totalRows,
            validRows: result.validRows,
            errorRows: result.errorRows,
            source: 'simplicity',
          });
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
          // Log telemetry for successful upload
          telemetry.intakeUploadSubmitted({
            batchId: result.batchId,
            filename: result.filename,
            rowCount: result.totalRows,
            validRows: result.validRows,
            errorRows: result.errorRows,
            source: 'simplicity',
          });
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
          Upload CSV
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => !isUploading && inputRef.current?.click()}
          className={cn(
            'relative flex flex-col items-center justify-center p-8 rounded-lg border-2 border-dashed transition-all duration-200 cursor-pointer',
            isDragOver
              ? 'border-indigo-500 bg-indigo-500/5'
              : 'border-slate-300 hover:border-indigo-400 hover:bg-slate-50',
            isUploading && 'pointer-events-none opacity-75'
          )}
        >
          {isUploading ? (
            <>
              <Loader2 className="h-12 w-12 text-indigo-500 animate-spin mb-3" />
              <p className="text-sm font-medium text-slate-700">
                {state.status === 'uploading' ? 'Uploading...' : 'Processing...'}
              </p>
              <div className="w-full max-w-xs mt-4">
                <div className="h-2 bg-slate-200 rounded-full overflow-hidden">
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
              <p className="text-sm font-medium text-emerald-700">Upload Complete!</p>
              <p className="text-xs text-slate-500 mt-1">
                {state.result?.validRows} of {state.result?.totalRows} rows valid
              </p>
              <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); reset(); }} className="mt-3">
                Upload Another
              </Button>
            </>
          ) : state.status === 'error' ? (
            <>
              <XCircle className="h-12 w-12 text-red-500 mb-3" />
              <p className="text-sm font-medium text-red-700">Upload Failed</p>
              <p className="text-xs text-slate-500 mt-1 text-center max-w-xs">{state.error}</p>
              <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); reset(); }} className="mt-3">
                Try Again
              </Button>
            </>
          ) : (
            <>
              <FileUp className="h-12 w-12 text-slate-400 mb-3" />
              <p className="text-sm font-medium text-slate-700">Drop CSV file here</p>
              <p className="text-xs text-slate-500 mt-1">or click to browse</p>
            </>
          )}
          <input
            ref={inputRef}
            type="file"
            accept=".csv"
            onChange={handleFileSelect}
            className="hidden"
          />
        </div>
      </CardContent>
    </Card>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// BATCH ROW
// ═══════════════════════════════════════════════════════════════════════════

interface BatchRowProps {
  batch: IntakeBatchSummary;
  isExpanded: boolean;
  onToggle: () => void;
}

const BatchRow: FC<BatchRowProps> = ({ batch, isExpanded, onToggle }) => {
  const hasErrors = batch.errorRows > 0;
  const ChevronIcon = isExpanded ? ChevronUp : ChevronDown;

  return (
    <div
      className={cn(
        'rounded-lg border transition-all duration-200',
        batch.status === 'failed'
          ? 'border-red-500/30 bg-red-500/5'
          : batch.status === 'processing'
            ? 'border-blue-500/30 bg-blue-500/5'
            : 'border-slate-200 bg-white'
      )}
    >
      <button
        onClick={hasErrors ? onToggle : undefined}
        className={cn(
          'w-full p-3 flex items-center gap-3 text-left',
          hasErrors && 'cursor-pointer hover:bg-slate-50'
        )}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-medium text-slate-900 truncate">
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
                <span>{formatDuration(batch.durationSeconds)}</span>
              </>
            )}
          </div>
        </div>
        {hasErrors && (
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-red-600">
              {batch.errorRows} error{batch.errorRows !== 1 ? 's' : ''}
            </span>
            <ChevronIcon className="h-4 w-4 text-slate-400" />
          </div>
        )}
      </button>

      {isExpanded && hasErrors && (
        <div className="px-3 pb-3 border-t border-slate-200">
          <div className="mt-3 p-3 bg-red-500/5 rounded text-xs">
            <div className="flex items-start gap-2">
              <AlertTriangle className="h-3.5 w-3.5 text-red-500 mt-0.5 flex-shrink-0" />
              <div>
                <p className="font-medium text-red-700">
                  {batch.errorRows} row{batch.errorRows !== 1 ? 's' : ''} failed validation
                </p>
                <p className="text-slate-600 mt-1">
                  Check the error log for details or re-upload with corrected data.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// BATCH HISTORY PANEL
// ═══════════════════════════════════════════════════════════════════════════

interface BatchHistoryPanelProps {
  batches: IntakeBatchSummary[];
  isLoading: boolean;
}

const BatchHistoryPanel: FC<BatchHistoryPanelProps> = ({ batches, isLoading }) => {
  const [expandedBatchId, setExpandedBatchId] = useState<string | null>(null);

  const toggleExpand = useCallback((batchId: string) => {
    setExpandedBatchId((prev) => (prev === batchId ? null : batchId));
  }, []);

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="pb-3 flex-shrink-0">
        <CardTitle className="flex items-center gap-2 text-base font-semibold">
          <FileText className="h-5 w-5 text-indigo-500" />
          Recent Batches
          <span className="ml-auto text-xs font-normal text-slate-500">
            {batches.length} batches
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <BatchRowSkeleton key={i} />
            ))}
          </div>
        ) : batches.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-slate-500">
            <Database className="h-8 w-8 mb-2 opacity-50" />
            <p className="text-sm">No batches yet</p>
            <p className="text-xs mt-1">Upload a CSV to get started</p>
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
// MAIN PAGE COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const IntakeStationPage: FC = () => {
  const { triggerRefresh, isRefreshing } = useRefreshBus();
  const {
    radar,
    batches,
    isLoading,
    error,
    lastUpdated,
    refetch,
  } = useIntakeStationData();

  const handleUploadComplete = useCallback(() => {
    refetch();
  }, [refetch]);

  // Calculate summary stats from batches
  const batchStats = useMemo(() => {
    const last24h = batches.filter(
      (b) => new Date(b.createdAt).getTime() > Date.now() - 24 * 60 * 60 * 1000
    );
    const completed = last24h.filter((b) => b.status === 'completed').length;
    const failed = last24h.filter((b) => b.status === 'failed').length;
    const processing = batches.filter((b) => b.status === 'processing').length;
    return { completed, failed, processing };
  }, [batches]);

  return (
    <div className="min-h-screen bg-slate-50/50">
      {/* Header */}
      <PageHeader
        title="Intake Station"
        description="Upload judgment data, monitor processing, and track intake pipeline health"
        badge={<Upload className="h-5 w-5 text-indigo-500" />}
        actions={
          <div className="flex items-center gap-2">
            {lastUpdated && (
              <span className="text-xs text-slate-500">
                Updated {formatDateTime(lastUpdated.toISOString())}
              </span>
            )}
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
          </div>
        }
      />

      <div className="p-6 space-y-6">
        {/* Error Banner */}
        {error && (
          <div className="flex items-center gap-3 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
            <AlertCircle className="h-5 w-5 flex-shrink-0" />
            <div>
              <p className="font-medium">Unable to load intake data</p>
              <p className="text-sm text-red-600">{error}</p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => refetch()} className="ml-auto">
              Retry
            </Button>
          </div>
        )}

        {/* Radar Metrics */}
        <section>
          <h2 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-indigo-500" />
            Intake Radar
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
            {isLoading ? (
              Array.from({ length: 7 }).map((_, i) => <MetricCardSkeleton key={i} />)
            ) : (
              <>
                <MetricCard
                  icon={TrendingUp}
                  iconColor="text-blue-500"
                  label="Judgments (24h)"
                  value={radar?.judgmentsIngested24h ?? '—'}
                  valueColor="text-blue-600"
                />
                <MetricCard
                  icon={TrendingUp}
                  iconColor="text-indigo-500"
                  label="Judgments (7d)"
                  value={radar?.judgmentsIngested7d ?? '—'}
                  valueColor="text-indigo-600"
                />
                <MetricCard
                  icon={DollarSign}
                  iconColor="text-emerald-500"
                  label="New AUM (24h)"
                  value={radar ? formatCurrency(radar.newAum24h) : '—'}
                  valueColor="text-emerald-600"
                />
                <MetricCard
                  icon={CheckCircle2}
                  iconColor="text-green-500"
                  label="Validity Rate"
                  value={radar ? `${radar.validityRate24h.toFixed(1)}%` : '—'}
                  valueColor="text-green-600"
                />
                <MetricCard
                  icon={Clock}
                  iconColor="text-amber-500"
                  label="Queue Pending"
                  value={radar?.queueDepthPending ?? '—'}
                  valueColor="text-amber-600"
                />
                <MetricCard
                  icon={AlertTriangle}
                  iconColor="text-red-500"
                  label="Critical Failures"
                  value={radar?.criticalFailures24h ?? '—'}
                  valueColor={radar?.criticalFailures24h ? 'text-red-600' : 'text-slate-600'}
                />
                <MetricCard
                  icon={Zap}
                  iconColor="text-purple-500"
                  label="Avg Process Time"
                  value={radar ? `${radar.avgProcessingTimeSeconds.toFixed(1)}s` : '—'}
                  valueColor="text-purple-600"
                />
              </>
            )}
          </div>
        </section>

        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Upload Zone */}
          <div className="lg:col-span-1">
            <UploadZone onUploadComplete={handleUploadComplete} />

            {/* Quick Stats */}
            <Card className="mt-4">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <Activity className="h-4 w-4 text-indigo-500" />
                  Today's Activity
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-3 gap-3 text-center">
                  <div>
                    <div className="text-2xl font-bold text-emerald-600">
                      {batchStats.completed}
                    </div>
                    <div className="text-xs text-slate-500">Completed</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-blue-600">
                      {batchStats.processing}
                    </div>
                    <div className="text-xs text-slate-500">Processing</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-red-600">
                      {batchStats.failed}
                    </div>
                    <div className="text-xs text-slate-500">Failed</div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Batch History */}
          <div className="lg:col-span-2">
            <BatchHistoryPanel batches={batches} isLoading={isLoading} />
          </div>
        </div>

        {/* How It Works */}
        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-900 mb-4">
            How Intake Processing Works
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6 text-sm text-slate-600">
            <div>
              <div className="flex items-center gap-2 font-medium text-slate-800 mb-2">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-100 text-indigo-600 text-xs font-bold">
                  1
                </div>
                Upload
              </div>
              <p>Drop a Simplicity or JBI export CSV. We validate the file format instantly.</p>
            </div>
            <div>
              <div className="flex items-center gap-2 font-medium text-slate-800 mb-2">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-100 text-indigo-600 text-xs font-bold">
                  2
                </div>
                Parse & Validate
              </div>
              <p>Each row is parsed, normalized, and validated against our schema rules.</p>
            </div>
            <div>
              <div className="flex items-center gap-2 font-medium text-slate-800 mb-2">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-100 text-indigo-600 text-xs font-bold">
                  3
                </div>
                Enrich & Score
              </div>
              <p>Valid judgments are enriched with collectability scores and tier assignments.</p>
            </div>
            <div>
              <div className="flex items-center gap-2 font-medium text-slate-800 mb-2">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-100 text-indigo-600 text-xs font-bold">
                  4
                </div>
                Pipeline Ready
              </div>
              <p>Scored judgments enter the enforcement pipeline for automated processing.</p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};

export default IntakeStationPage;
