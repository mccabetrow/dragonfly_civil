/**
 * IntakeStationPage - Financial Terminal Style Intake Dashboard
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * PR-2: UI State Machine & Polling Fallback
 *
 * Architecture:
 *   - uploadRequestStatus: HTTP upload result (idle/uploading/success/error)
 *   - batchProcessingStatus: Worker-driven (pending/processing/completed/failed)
 *   - "Upload Error" only appears if POST request fails
 *   - Degraded Banner: shown when API returns degraded: true
 *
 * HFT-inspired intake operations dashboard:
 *   - Intake Radar metrics (24h/7d judgment counts, AUM, validity)
 *   - Animated drag-and-drop with glowing dropzone
 *   - Real-time progress bar during upload
 *   - Live batch history with polling (5s refresh)
 *   - Green flash animation on batch completion
 *
 * Design:
 *   - Dark theme: bg-slate-950, border-slate-800
 *   - Monospace numbers, green/red indicators
 *   - Skeleton loaders (no spinners)
 *   - framer-motion animations
 *
 * Route: /intake
 */
import { type FC, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload,
  FileText,
  CheckCircle2,
  XCircle,
  Clock,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Database,
  Loader2,
  TrendingUp,
  DollarSign,
  Activity,
  AlertCircle,
  BarChart3,
  FileUp,
  Timer,
  AlertTriangle,
  Check,
  WifiOff,
} from 'lucide-react';
import { cn } from '../lib/design-tokens';
import { useIntakeStationData, type IntakeBatchSummary } from '../hooks/useIntakeStationData';
import { useUploadIntake, type DataSource } from '../hooks/useUploadIntake';
import { useOnRefresh } from '../context/RefreshContext';
import { useJobQueueRealtime } from '../hooks/useRealtimeSubscription';

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function formatCurrency(value: number): string {
  if (value >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(2)}M`;
  }
  if (value >= 1_000) {
    return `$${(value / 1_000).toFixed(0)}K`;
  }
  return `$${value.toFixed(0)}`;
}

function formatNumber(value: number): string {
  return value.toLocaleString();
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

function formatTimeAgo(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}

// ═══════════════════════════════════════════════════════════════════════════
// SKELETON COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

const MetricCardSkeleton: FC = () => (
  <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4 animate-pulse">
    <div className="h-3 w-20 bg-slate-700 rounded mb-3" />
    <div className="h-7 w-16 bg-slate-700 rounded" />
  </div>
);

const BatchRowSkeleton: FC = () => (
  <div className="p-4 border-b border-slate-800 animate-pulse">
    <div className="flex items-center gap-4">
      <div className="h-8 w-8 bg-slate-800 rounded-md" />
      <div className="flex-1">
        <div className="h-4 w-48 bg-slate-700 rounded mb-2" />
        <div className="h-3 w-32 bg-slate-800 rounded" />
      </div>
      <div className="h-6 w-24 bg-slate-800 rounded-full" />
    </div>
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// INTAKE RADAR METRICS
// ═══════════════════════════════════════════════════════════════════════════

interface IntakeRadarProps {
  data: {
    judgmentsIngested24h: number;
    judgmentsIngested7d: number;
    newAum24h: number;
    validityRate24h: number;
    queueDepthPending: number;
    criticalFailures24h: number;
    avgProcessingTimeSeconds: number;
  } | null;
  isLoading: boolean;
}

const IntakeRadar: FC<IntakeRadarProps> = ({ data, isLoading }) => {
  if (isLoading || !data) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        {Array.from({ length: 7 }).map((_, i) => (
          <MetricCardSkeleton key={i} />
        ))}
      </div>
    );
  }

  const metrics = [
    {
      label: 'Judgments 24h',
      value: formatNumber(data.judgmentsIngested24h),
      icon: TrendingUp,
      color: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
    },
    {
      label: 'Judgments 7d',
      value: formatNumber(data.judgmentsIngested7d),
      icon: BarChart3,
      color: 'text-blue-400',
      bgColor: 'bg-blue-500/10',
    },
    {
      label: 'New AUM 24h',
      value: formatCurrency(data.newAum24h),
      icon: DollarSign,
      color: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
    },
    {
      label: 'Validity Rate',
      value: `${data.validityRate24h.toFixed(1)}%`,
      icon: Activity,
      color: data.validityRate24h >= 90 ? 'text-emerald-400' : 'text-amber-400',
      bgColor: data.validityRate24h >= 90 ? 'bg-emerald-500/10' : 'bg-amber-500/10',
    },
    {
      label: 'Queue Depth',
      value: formatNumber(data.queueDepthPending),
      icon: Database,
      color: data.queueDepthPending > 50 ? 'text-amber-400' : 'text-slate-400',
      bgColor: 'bg-slate-800/50',
    },
    {
      label: 'Failures 24h',
      value: formatNumber(data.criticalFailures24h),
      icon: AlertCircle,
      color: data.criticalFailures24h > 0 ? 'text-red-400' : 'text-slate-500',
      bgColor: data.criticalFailures24h > 0 ? 'bg-red-500/10' : 'bg-slate-800/50',
    },
    {
      label: 'Avg Time',
      value: `${data.avgProcessingTimeSeconds.toFixed(1)}s`,
      icon: Timer,
      color: 'text-slate-400',
      bgColor: 'bg-slate-800/50',
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
      {metrics.map((metric) => (
        <motion.div
          key={metric.label}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className={cn(
            'rounded-lg border border-slate-800 p-3',
            metric.bgColor
          )}
        >
          <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-500 font-mono mb-1">
            <metric.icon className={cn('h-3 w-3', metric.color)} />
            {metric.label}
          </div>
          <div className={cn('text-xl font-bold font-mono', metric.color)}>
            {metric.value}
          </div>
        </motion.div>
      ))}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// DATA SOURCE SELECTOR
// ═══════════════════════════════════════════════════════════════════════════

const DATA_SOURCES: { value: DataSource; label: string; description: string }[] = [
  { value: 'simplicity', label: 'Simplicity', description: 'Standard Simplicity exports' },
  { value: 'jbi', label: 'JBI', description: 'JBI system exports' },
  { value: 'foil', label: 'FOIL', description: 'Court data dumps (large files)' },
  { value: 'manual', label: 'Manual', description: 'Generic CSV uploads' },
];

interface DataSourceSelectorProps {
  value: DataSource;
  onChange: (value: DataSource) => void;
}

const DataSourceSelector: FC<DataSourceSelectorProps> = ({ value, onChange }) => {
  return (
    <div className="flex items-center gap-2 mb-4">
      <span className="text-xs text-slate-500 font-mono uppercase tracking-wider">Source:</span>
      <div className="flex gap-1">
        {DATA_SOURCES.map((source) => (
          <button
            key={source.value}
            type="button"
            onClick={() => onChange(source.value)}
            title={source.description}
            className={cn(
              'px-3 py-1 rounded text-xs font-mono transition-all',
              value === source.value
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/50'
                : 'bg-slate-800/50 text-slate-500 border border-slate-700 hover:border-slate-600 hover:text-slate-400'
            )}
          >
            {source.label}
          </button>
        ))}
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// ANIMATED DROPZONE
// ═══════════════════════════════════════════════════════════════════════════

interface AnimatedDropzoneProps {
  onUploadComplete: () => void;
}

const AnimatedDropzone: FC<AnimatedDropzoneProps> = ({ onUploadComplete }) => {
  const { state, uploadFile, reset, source, setSource } = useUploadIntake();
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    // Only set to false if we're leaving the dropzone entirely
    const relatedTarget = e.relatedTarget as HTMLElement;
    if (!relatedTarget || !e.currentTarget.contains(relatedTarget)) {
      setIsDragOver(false);
    }
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
      e.target.value = '';
    },
    [uploadFile, onUploadComplete]
  );

  const handleClick = useCallback(() => {
    if (state.status === 'idle' || state.status === 'error') {
      inputRef.current?.click();
    }
  }, [state.status]);

  const handleReset = useCallback(() => {
    reset();
  }, [reset]);

  // Determine zone state
  const isUploading = state.status === 'uploading' || state.status === 'processing';
  const isSuccess = state.status === 'success';
  const isError = state.status === 'error';
  const isIdle = state.status === 'idle';

  return (
    <div className="flex flex-col">
      {/* Data Source Selector - shown in idle state */}
      {isIdle && (
        <DataSourceSelector
          value={source}
          onChange={(v) => setSource(v)}
        />
      )}
      
      <motion.div
        className={cn(
          'relative rounded-xl border-2 border-dashed transition-all duration-300',
          'flex flex-col items-center justify-center py-12 px-6',
          'cursor-pointer',
          // Drag over glow effect
          isDragOver && 'border-emerald-400 bg-emerald-500/10 shadow-[0_0_40px_rgba(16,185,129,0.3)]',
          // Normal states
          !isDragOver && isIdle && 'border-slate-700 bg-slate-900/50 hover:border-slate-600 hover:bg-slate-900/80',
          isUploading && 'border-blue-500/50 bg-blue-500/5',
          isSuccess && 'border-emerald-500/50 bg-emerald-500/5',
          isError && 'border-red-500/50 bg-red-500/5'
        )}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        animate={{
          scale: isDragOver ? 1.02 : 1,
        }}
        transition={{ type: 'spring', stiffness: 300, damping: 20 }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv"
          onChange={handleFileSelect}
          className="hidden"
        />

        <AnimatePresence mode="wait">
          {/* Idle State */}
          {isIdle && !isDragOver && (
            <motion.div
              key="idle"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
            className="flex flex-col items-center text-center"
          >
            <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-slate-800/80 mb-4">
              <Upload className="h-8 w-8 text-slate-400" />
            </div>
            <h3 className="text-lg font-semibold text-white mb-1 font-mono">
              Drop CSV to Import
            </h3>
            <p className="text-sm text-slate-500 mb-4">
              Simplicity, JBI, or any valid judgment export
            </p>
            <div className="flex items-center gap-2">
              <span className="px-3 py-1.5 rounded-md bg-slate-800 text-xs text-slate-400 font-mono">
                .CSV
              </span>
              <span className="text-slate-600">•</span>
              <span className="text-xs text-slate-500">Max 50MB</span>
            </div>
          </motion.div>
        )}

        {/* Drag Over State */}
        {isDragOver && (
          <motion.div
            key="dragover"
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.9 }}
            className="flex flex-col items-center text-center"
          >
            <motion.div
              className="flex h-20 w-20 items-center justify-center rounded-xl bg-emerald-500/20 mb-4"
              animate={{
                boxShadow: [
                  '0 0 20px rgba(16,185,129,0.3)',
                  '0 0 40px rgba(16,185,129,0.5)',
                  '0 0 20px rgba(16,185,129,0.3)',
                ],
              }}
              transition={{ duration: 1.5, repeat: Infinity }}
            >
              <FileUp className="h-10 w-10 text-emerald-400" />
            </motion.div>
            <h3 className="text-xl font-bold text-emerald-400 font-mono">
              Release to Upload
            </h3>
          </motion.div>
        )}

        {/* Uploading State */}
        {isUploading && (
          <motion.div
            key="uploading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center text-center w-full max-w-md"
          >
            <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-blue-500/20 mb-4">
              <Loader2 className="h-8 w-8 text-blue-400 animate-spin" />
            </div>
            <h3 className="text-lg font-semibold text-white mb-2 font-mono">
              {state.status === 'uploading' ? 'Uploading...' : 'Processing...'}
            </h3>
            
            {/* Progress Bar */}
            <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden mb-2">
              <motion.div
                className="h-full bg-blue-500"
                initial={{ width: '0%' }}
                animate={{ width: `${state.progress}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
            <p className="text-sm text-slate-500 font-mono">{state.progress}%</p>
          </motion.div>
        )}

        {/* Success State */}
        {isSuccess && state.result && (
          <motion.div
            key="success"
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center text-center"
          >
            <motion.div
              className="flex h-16 w-16 items-center justify-center rounded-xl bg-emerald-500/20 mb-4"
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ type: 'spring', stiffness: 400, damping: 15 }}
            >
              <CheckCircle2 className="h-8 w-8 text-emerald-400" />
            </motion.div>
            <h3 className="text-lg font-semibold text-emerald-400 mb-2 font-mono">
              Upload Complete
            </h3>
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="text-center">
                <p className="text-2xl font-bold text-white font-mono">{state.result.totalRows}</p>
                <p className="text-xs text-slate-500">Total Rows</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-emerald-400 font-mono">{state.result.validRows}</p>
                <p className="text-xs text-slate-500">Valid</p>
              </div>
              <div className="text-center">
                <p className={cn(
                  'text-2xl font-bold font-mono',
                  state.result.errorRows > 0 ? 'text-red-400' : 'text-slate-500'
                )}>
                  {state.result.errorRows}
                </p>
                <p className="text-xs text-slate-500">Errors</p>
              </div>
            </div>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                handleReset();
              }}
              className="px-4 py-2 rounded-md bg-slate-800 text-slate-300 text-sm font-mono hover:bg-slate-700 transition-colors"
            >
              Upload Another
            </button>
          </motion.div>
        )}

        {/* Error State */}
        {isError && (
          <motion.div
            key="error"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center text-center"
          >
            <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-red-500/20 mb-4">
              <XCircle className="h-8 w-8 text-red-400" />
            </div>
            <h3 className="text-lg font-semibold text-red-400 mb-2 font-mono">
              Upload Failed
            </h3>
            <p className="text-sm text-slate-400 mb-4 max-w-sm">
              {state.error || 'An unknown error occurred'}
            </p>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                handleReset();
              }}
              className="px-4 py-2 rounded-md bg-slate-800 text-slate-300 text-sm font-mono hover:bg-slate-700 transition-colors"
            >
              Try Again
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// BATCH STATUS BADGE
// ═══════════════════════════════════════════════════════════════════════════

type BatchStatus = 'pending' | 'processing' | 'completed' | 'failed';

interface StatusConfig {
  icon: typeof CheckCircle2;
  label: string;
  className: string;
}

const STATUS_CONFIG: Record<BatchStatus, StatusConfig> = {
  completed: {
    icon: CheckCircle2,
    label: 'Complete',
    className: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
  },
  failed: {
    icon: XCircle,
    label: 'Failed',
    className: 'bg-red-500/10 text-red-400 border-red-500/30',
  },
  processing: {
    icon: Loader2,
    label: 'Processing',
    className: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
  },
  pending: {
    icon: Clock,
    label: 'Pending',
    className: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  },
};

const StatusBadge: FC<{ status: BatchStatus }> = ({ status }) => {
  const config = STATUS_CONFIG[status];
  const Icon = config.icon;
  const isAnimated = status === 'processing';

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-mono font-medium border',
        config.className
      )}
    >
      <Icon className={cn('h-3 w-3', isAnimated && 'animate-spin')} />
      {config.label}
    </span>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// BATCH HISTORY TABLE
// ═══════════════════════════════════════════════════════════════════════════

interface BatchHistoryProps {
  batches: IntakeBatchSummary[];
  isLoading: boolean;
  previousBatches: IntakeBatchSummary[];
}

const BatchHistory: FC<BatchHistoryProps> = ({ batches, isLoading, previousBatches }) => {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  // Detect batches that just completed (were processing, now completed)
  const justCompleted = useMemo(() => {
    const completedIds = new Set<string>();
    batches.forEach((batch) => {
      if (batch.status === 'completed') {
        const prev = previousBatches.find((p) => p.id === batch.id);
        if (prev && prev.status === 'processing') {
          completedIds.add(batch.id);
        }
      }
    });
    return completedIds;
  }, [batches, previousBatches]);

  if (isLoading && batches.length === 0) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900/50 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800">
          <h3 className="text-sm font-semibold text-white font-mono">Batch History</h3>
        </div>
        {Array.from({ length: 5 }).map((_, i) => (
          <BatchRowSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (batches.length === 0) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-8 text-center">
        <Database className="h-10 w-10 text-slate-600 mx-auto mb-3" />
        <h3 className="text-sm font-semibold text-slate-400 font-mono mb-1">No Batches Yet</h3>
        <p className="text-xs text-slate-600">Upload a CSV to start importing judgments</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white font-mono">Batch History</h3>
        <span className="text-xs text-slate-500 font-mono">{batches.length} batches</span>
      </div>

      {/* Table Header */}
      <div className="grid grid-cols-12 gap-2 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-600 font-mono border-b border-slate-800/50 bg-slate-950/30">
        <div className="col-span-4">File</div>
        <div className="col-span-2">Status</div>
        <div className="col-span-2 text-right">Rows</div>
        <div className="col-span-2 text-right">Success</div>
        <div className="col-span-2 text-right">Time</div>
      </div>

      {/* Rows */}
      <div className="divide-y divide-slate-800/50">
        {batches.map((batch) => {
          const isExpanded = expandedIds.has(batch.id);
          const isJustCompleted = justCompleted.has(batch.id);

          return (
            <motion.div
              key={batch.id}
              initial={isJustCompleted ? { backgroundColor: 'rgba(16,185,129,0.2)' } : undefined}
              animate={{ backgroundColor: 'transparent' }}
              transition={{ duration: 2 }}
            >
              {/* Main Row */}
              <button
                type="button"
                onClick={() => toggleExpand(batch.id)}
                className={cn(
                  'w-full grid grid-cols-12 gap-2 px-4 py-3 text-left',
                  'hover:bg-slate-800/30 transition-colors',
                  isJustCompleted && 'animate-pulse-once'
                )}
              >
                {/* File */}
                <div className="col-span-4 flex items-center gap-2 min-w-0">
                  <FileText className="h-4 w-4 text-slate-500 flex-shrink-0" />
                  <div className="min-w-0">
                    <p className="text-sm text-white font-mono truncate">{batch.filename}</p>
                    <p className="text-xs text-slate-600">{formatTimeAgo(batch.createdAt)}</p>
                  </div>
                </div>

                {/* Status */}
                <div className="col-span-2 flex items-center">
                  <StatusBadge status={batch.status} />
                </div>

                {/* Rows */}
                <div className="col-span-2 text-right font-mono">
                  <span className="text-sm text-white">{formatNumber(batch.totalRows)}</span>
                </div>

                {/* Success Rate */}
                <div className="col-span-2 text-right font-mono">
                  <span
                    className={cn(
                      'text-sm',
                      batch.successRate >= 95 ? 'text-emerald-400' : batch.successRate >= 80 ? 'text-amber-400' : 'text-red-400'
                    )}
                  >
                    {batch.successRate.toFixed(1)}%
                  </span>
                </div>

                {/* Duration / Expand */}
                <div className="col-span-2 flex items-center justify-end gap-2">
                  <span className="text-sm text-slate-500 font-mono">
                    {formatDuration(batch.durationSeconds)}
                  </span>
                  {isExpanded ? (
                    <ChevronUp className="h-4 w-4 text-slate-600" />
                  ) : (
                    <ChevronDown className="h-4 w-4 text-slate-600" />
                  )}
                </div>
              </button>

              {/* Expanded Details */}
              <AnimatePresence>
                {isExpanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden"
                  >
                    <div className="px-4 pb-4 pt-2 bg-slate-900/30 grid grid-cols-4 gap-4 text-xs">
                      <div>
                        <span className="text-slate-600 block mb-1">Source</span>
                        <span className="text-slate-300 font-mono uppercase">{batch.source}</span>
                      </div>
                      <div>
                        <span className="text-slate-600 block mb-1">Valid Rows</span>
                        <span className="text-emerald-400 font-mono">{formatNumber(batch.validRows)}</span>
                      </div>
                      <div>
                        <span className="text-slate-600 block mb-1">Error Rows</span>
                        <span className={cn('font-mono', batch.errorRows > 0 ? 'text-red-400' : 'text-slate-500')}>
                          {formatNumber(batch.errorRows)}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-600 block mb-1">Completed</span>
                        <span className="text-slate-300 font-mono">{formatDateTime(batch.completedAt)}</span>
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// DEGRADED MODE BANNER
// ═══════════════════════════════════════════════════════════════════════════

interface DegradedBannerProps {
  visible: boolean;
}

const DegradedBanner: FC<DegradedBannerProps> = ({ visible }) => {
  if (!visible) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 flex items-center gap-3"
    >
      <WifiOff className="h-5 w-5 text-amber-400 flex-shrink-0" />
      <div>
        <p className="text-sm font-medium text-amber-300">
          Live updates paused
        </p>
        <p className="text-xs text-amber-400/70">
          Data may be delayed. Polling continues in the background.
        </p>
      </div>
    </motion.div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════════════════════════

const IntakeStationPage: FC = () => {
  // PR-2: Extract isDegraded from hook for conditional banner display
  const { 
    radar, 
    batches, 
    isLoading, 
    refetch, 
    startPolling, 
    stopPolling, 
    isPolling,
    isDegraded,
    isRealtimeConnected,
  } = useIntakeStationData();
  
  const [previousBatches, setPreviousBatches] = useState<IntakeBatchSummary[]>([]);
  const [realtimeFlash, setRealtimeFlash] = useState(false);

  // ═══════════════════════════════════════════════════════════════════════════
  // REALTIME SUBSCRIPTION - Auto-refetch when jobs complete (SECONDARY)
  // Polling runs independently - realtime is an enhancement only
  // ═══════════════════════════════════════════════════════════════════════════
  const { isConnected: realtimeConnected } = useJobQueueRealtime({
    onJobComplete: (jobId, status) => {
      console.log(`[Realtime] Job ${jobId} completed with status: ${status}`);
      if (status === 'completed' || status === 'failed') {
        // Trigger flash animation
        setRealtimeFlash(true);
        setTimeout(() => setRealtimeFlash(false), 2000);
        // Refetch data
        refetch();
      }
    },
    onFlash: () => {
      setRealtimeFlash(true);
      setTimeout(() => setRealtimeFlash(false), 2000);
    },
  });

  // Subscribe to global refresh
  useOnRefresh(() => {
    refetch();
  });

  // Track previous batches for flash animation
  useEffect(() => {
    if (batches.length > 0) {
      // Only update previous if we have new data
      setPreviousBatches((prev) => {
        // Keep previous for comparison, update after a delay
        setTimeout(() => {
          setPreviousBatches(batches);
        }, 2000);
        return prev;
      });
    }
  }, [batches]);

  // Polling is enabled by default in the hook (PR-2)
  // startPolling/stopPolling are still exposed for manual control
  useEffect(() => {
    startPolling();
    return () => stopPolling();
  }, [startPolling, stopPolling]);

  const handleUploadComplete = useCallback(() => {
    refetch();
  }, [refetch]);

  return (
    <div className={cn(
      'space-y-6 transition-all duration-500',
      realtimeFlash && 'ring-2 ring-emerald-500/30 ring-inset rounded-lg'
    )}>
      {/* Flash overlay */}
      <AnimatePresence>
        {realtimeFlash && (
          <motion.div
            className="fixed inset-0 bg-emerald-500/5 pointer-events-none z-50"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
          />
        )}
      </AnimatePresence>

      {/* PR-2: Degraded Mode Banner - shown when API returns degraded: true */}
      <AnimatePresence>
        <DegradedBanner visible={isDegraded} />
      </AnimatePresence>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white font-mono tracking-tight">
            INTAKE STATION
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Real-time judgment ingestion • {
              isDegraded 
                ? 'Degraded mode' 
                : realtimeConnected || isRealtimeConnected
                  ? 'Realtime connected' 
                  : isPolling 
                    ? 'Polling active' 
                    : 'Paused'
            }
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Degraded indicator */}
          {isDegraded && (
            <div className="flex items-center gap-2 text-xs text-amber-400 font-mono">
              <WifiOff className="h-3.5 w-3.5" />
              Degraded
            </div>
          )}
          {/* Realtime indicator */}
          {!isDegraded && (realtimeConnected || isRealtimeConnected) && (
            <div className="flex items-center gap-2 text-xs text-emerald-400 font-mono">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              Realtime
            </div>
          )}
          {/* Polling indicator (shown when realtime is down but polling continues) */}
          {!isDegraded && !(realtimeConnected || isRealtimeConnected) && isPolling && (
            <div className="flex items-center gap-2 text-xs text-slate-500 font-mono">
              <span className="h-2 w-2 rounded-full bg-amber-400 animate-pulse" />
              Polling
            </div>
          )}
          {/* Manual refresh */}
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isLoading}
            className={cn(
              'flex items-center gap-2 px-3 py-1.5 rounded-md',
              'bg-slate-800 border border-slate-700 text-slate-300',
              'hover:bg-slate-700 transition-colors text-sm font-mono',
              'disabled:opacity-50'
            )}
          >
            <RefreshCw className={cn('h-3.5 w-3.5', isLoading && 'animate-spin')} />
            Refresh
          </button>
        </div>
      </div>

      {/* Intake Radar Metrics */}
      <IntakeRadar data={radar} isLoading={isLoading && !radar} />

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Upload Zone */}
        <div>
          <h2 className="text-sm font-semibold text-slate-400 font-mono uppercase tracking-wider mb-3">
            Upload
          </h2>
          <AnimatedDropzone onUploadComplete={handleUploadComplete} />
        </div>

        {/* Quick Stats */}
        <div>
          <h2 className="text-sm font-semibold text-slate-400 font-mono uppercase tracking-wider mb-3">
            Processing Status
          </h2>
          <div className="grid grid-cols-2 gap-3">
            {/* In Progress */}
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <div className="flex items-center gap-2 mb-2">
                <Loader2 className="h-4 w-4 text-blue-400 animate-spin" />
                <span className="text-xs text-slate-500 font-mono uppercase">Processing</span>
              </div>
              <p className="text-3xl font-bold text-white font-mono">
                {batches.filter((b) => b.status === 'processing').length}
              </p>
            </div>

            {/* Pending */}
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <div className="flex items-center gap-2 mb-2">
                <Clock className="h-4 w-4 text-amber-400" />
                <span className="text-xs text-slate-500 font-mono uppercase">Pending</span>
              </div>
              <p className="text-3xl font-bold text-white font-mono">
                {batches.filter((b) => b.status === 'pending').length}
              </p>
            </div>

            {/* Completed Today */}
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <div className="flex items-center gap-2 mb-2">
                <Check className="h-4 w-4 text-emerald-400" />
                <span className="text-xs text-slate-500 font-mono uppercase">Completed</span>
              </div>
              <p className="text-3xl font-bold text-emerald-400 font-mono">
                {batches.filter((b) => b.status === 'completed').length}
              </p>
            </div>

            {/* Failed */}
            <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="h-4 w-4 text-red-400" />
                <span className="text-xs text-slate-500 font-mono uppercase">Failed</span>
              </div>
              <p className={cn(
                'text-3xl font-bold font-mono',
                batches.filter((b) => b.status === 'failed').length > 0 ? 'text-red-400' : 'text-slate-500'
              )}>
                {batches.filter((b) => b.status === 'failed').length}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Batch History Table */}
      <BatchHistory 
        batches={batches} 
        isLoading={isLoading} 
        previousBatches={previousBatches}
      />
    </div>
  );
};

export default IntakeStationPage;
