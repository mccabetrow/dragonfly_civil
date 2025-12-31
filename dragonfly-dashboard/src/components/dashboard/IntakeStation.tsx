/**
 * IntakeStation Component - World-Class File Intake
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * A hedge-fund grade CSV upload component for the Dragonfly intake pipeline.
 *
 * Features:
 *   - Polling-based status updates (2s interval)
 *   - Error budget enforcement with rejection display
 *   - Processing metrics (parse time, DB time, throughput)
 *   - Recent errors table with download capability
 *   - Financial terminal aesthetic
 *
 * States:
 *   🟢 Success: "Batch Complete. 5,000 Rows Ingested."
 *   🟡 Partial: "Batch Complete with Warnings. 4,950 Ingested, 50 Errors."
 *   🔴 Failed: "Batch Rejected. Error Rate 15% > 10% Budget."
 *
 * Usage:
 *   <IntakeStation onUploadComplete={(batchId, result) => refetch()} />
 */

import { type FC, useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload,
  FileUp,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertTriangle,
  RefreshCw,
  AlertCircle,
  Clock,
  Database,
  Zap,
  Download,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import {
  api,
  type DataSourceType,
  type BatchUploadResponse,
  type BatchStatusResult,
  type BatchRowError,
} from '../../lib/api';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface IntakeStationProps {
  /**
   * Called when a batch is successfully completed (not just uploaded).
   * Use this to invalidate cache or refetch batch history.
   */
  onUploadComplete?: (batchId: string, result: BatchStatusResult) => void;

  /**
   * Optional className for the container.
   */
  className?: string;

  /**
   * Disable uploads (e.g., when backend is disconnected).
   */
  disabled?: boolean;
}

/**
 * Component state machine.
 * Transitions: idle → uploading → processing → (success | partial | error)
 */
type UploadState = 'idle' | 'uploading' | 'processing' | 'success' | 'partial' | 'error';

// ═══════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 60; // 2 minutes max
const MAX_ERRORS_TO_SHOW = 5;

// ═══════════════════════════════════════════════════════════════════════════
// DATA SOURCES
// ═══════════════════════════════════════════════════════════════════════════

const DATA_SOURCES: { value: DataSourceType; label: string; description: string }[] = [
  { value: 'simplicity', label: 'Simplicity', description: 'Standard Simplicity exports' },
  { value: 'jbi', label: 'JBI', description: 'JBI system exports' },
  { value: 'foil', label: 'FOIL', description: 'Court data dumps (large files)' },
  { value: 'manual', label: 'Manual', description: 'Generic CSV uploads' },
];

// ═══════════════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

function formatDuration(ms: number | null): string {
  if (ms === null) return '--';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function formatThroughput(rows: number, totalMs: number | null): string {
  if (!totalMs || totalMs === 0) return '--';
  const rowsPerSec = (rows / totalMs) * 1000;
  return `${rowsPerSec.toFixed(0)} rows/s`;
}

function downloadErrorsCsv(errors: BatchRowError[], filename: string): void {
  const headers = ['Row', 'Error Code', 'Error Message'];
  const rows = errors.map((e) => [
    (e.rowIndex + 1).toString(),
    e.errorCode,
    `"${e.errorMessage.replace(/"/g, '""')}"`,
  ]);

  const csv = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);

  const a = document.createElement('a');
  a.href = url;
  a.download = `errors_${filename.replace('.csv', '')}_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ═══════════════════════════════════════════════════════════════════════════
// DATA SOURCE SELECTOR
// ═══════════════════════════════════════════════════════════════════════════

interface DataSourceSelectorProps {
  value: DataSourceType;
  onChange: (value: DataSourceType) => void;
}

const DataSourceSelector: FC<DataSourceSelectorProps> = ({ value, onChange }) => (
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

// ═══════════════════════════════════════════════════════════════════════════
// PROCESSING METRICS COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

interface ProcessingMetricsProps {
  result: BatchStatusResult;
}

const ProcessingMetrics: FC<ProcessingMetricsProps> = ({ result }) => {
  const totalMs =
    (result.parseDurationMs ?? 0) + (result.dbDurationMs ?? 0) || null;

  return (
    <div className="mt-4 w-full max-w-lg">
      <div className="flex items-center gap-2 mb-2">
        <Zap className="h-3 w-3 text-amber-400" />
        <span className="text-xs text-slate-400 font-mono uppercase tracking-wider">
          Processing Metrics
        </span>
      </div>
      <div className="bg-slate-900/80 rounded-lg border border-slate-700/50 p-3">
        <div className="grid grid-cols-3 gap-4 text-center">
          {/* Parse Time */}
          <div className="flex flex-col items-center">
            <Clock className="h-4 w-4 text-blue-400 mb-1" />
            <span className="text-xs text-slate-500 font-mono">Parse</span>
            <span className="text-sm font-bold text-white font-mono">
              {formatDuration(result.parseDurationMs)}
            </span>
          </div>
          {/* DB Time */}
          <div className="flex flex-col items-center">
            <Database className="h-4 w-4 text-emerald-400 mb-1" />
            <span className="text-xs text-slate-500 font-mono">DB</span>
            <span className="text-sm font-bold text-white font-mono">
              {formatDuration(result.dbDurationMs)}
            </span>
          </div>
          {/* Throughput */}
          <div className="flex flex-col items-center">
            <Zap className="h-4 w-4 text-amber-400 mb-1" />
            <span className="text-xs text-slate-500 font-mono">Throughput</span>
            <span className="text-sm font-bold text-white font-mono">
              {formatThroughput(result.rowCountTotal, totalMs)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// ERROR TABLE COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

interface ErrorTableProps {
  errors: BatchRowError[];
  totalErrors: number;
  filename: string;
}

const ErrorTable: FC<ErrorTableProps> = ({ errors, totalErrors, filename }) => {
  const [expanded, setExpanded] = useState(false);
  const displayErrors = expanded ? errors : errors.slice(0, MAX_ERRORS_TO_SHOW);

  return (
    <div className="mt-4 w-full max-w-lg">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-red-400 font-mono uppercase tracking-wider">
          Recent Errors ({totalErrors} total)
        </span>
        <button
          type="button"
          onClick={() => downloadErrorsCsv(errors, filename)}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs font-mono text-slate-400 hover:text-white hover:bg-slate-800 transition-all"
        >
          <Download className="h-3 w-3" />
          Download All
        </button>
      </div>
      <div className="bg-slate-900/80 rounded-lg border border-red-500/20 overflow-hidden">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="bg-slate-800/50 text-slate-400">
              <th className="px-3 py-2 text-left w-16">Row</th>
              <th className="px-3 py-2 text-left w-32">Code</th>
              <th className="px-3 py-2 text-left">Message</th>
            </tr>
          </thead>
          <tbody>
            {displayErrors.map((err, idx) => (
              <tr
                key={idx}
                className="border-t border-slate-800 hover:bg-slate-800/30"
              >
                <td className="px-3 py-2 text-slate-500">{err.rowIndex + 1}</td>
                <td className="px-3 py-2 text-amber-400">{err.errorCode}</td>
                <td
                  className="px-3 py-2 text-red-400 truncate max-w-xs"
                  title={err.errorMessage}
                >
                  {err.errorMessage}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {totalErrors > MAX_ERRORS_TO_SHOW && (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="w-full py-2 text-xs font-mono text-slate-500 hover:text-white hover:bg-slate-800/50 transition-all flex items-center justify-center gap-1"
          >
            {expanded ? (
              <>
                <ChevronUp className="h-3 w-3" /> Show Less
              </>
            ) : (
              <>
                <ChevronDown className="h-3 w-3" /> Show All {totalErrors} Errors
              </>
            )}
          </button>
        )}
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// RESULT SUMMARY COMPONENT (WORLD-CLASS)
// ═══════════════════════════════════════════════════════════════════════════

interface ResultSummaryProps {
  result: BatchStatusResult;
  onReset: () => void;
}

const ResultSummary: FC<ResultSummaryProps> = ({ result, onReset }) => {
  // Determine result type
  const isSuccess =
    result.status === 'completed' && result.rowCountInvalid === 0;
  const isPartial =
    result.status === 'completed' && result.rowCountInvalid > 0;
  const isFailed = result.status === 'failed';

  // Calculate error rate
  const errorRate =
    result.rowCountTotal > 0
      ? ((result.rowCountInvalid / result.rowCountTotal) * 100).toFixed(1)
      : '0';

  return (
    <motion.div
      key="result"
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0 }}
      className="flex flex-col items-center text-center w-full"
    >
      {/* Icon */}
      <motion.div
        className={cn(
          'flex h-16 w-16 items-center justify-center rounded-xl mb-4',
          isSuccess && 'bg-emerald-500/20',
          isPartial && 'bg-amber-500/20',
          isFailed && 'bg-red-500/20'
        )}
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: 'spring', stiffness: 400, damping: 15 }}
      >
        {isSuccess && <CheckCircle2 className="h-8 w-8 text-emerald-400" />}
        {isPartial && <AlertCircle className="h-8 w-8 text-amber-400" />}
        {isFailed && <XCircle className="h-8 w-8 text-red-400" />}
      </motion.div>

      {/* Title - World Class Messaging */}
      <h3
        className={cn(
          'text-lg font-semibold mb-2 font-mono',
          isSuccess && 'text-emerald-400',
          isPartial && 'text-amber-400',
          isFailed && 'text-red-400'
        )}
      >
        {isSuccess && `🟢 Batch Complete. ${result.rowCountInserted.toLocaleString()} Rows Ingested.`}
        {isPartial &&
          `🟡 Batch Complete with Warnings. ${result.rowCountInserted.toLocaleString()} Ingested, ${result.rowCountInvalid.toLocaleString()} Errors.`}
        {isFailed && '🔴 Batch Rejected.'}
      </h3>

      {/* Rejection Reason (Failed Only) */}
      {isFailed && result.rejectionReason && (
        <div className="mb-4 px-4 py-2 rounded-lg bg-red-500/10 border border-red-500/30">
          <p className="text-sm text-red-400 font-mono">{result.rejectionReason}</p>
        </div>
      )}

      {/* Error Budget Violation (Failed Only) */}
      {isFailed && !result.rejectionReason && result.errorSummary && (
        <div className="mb-4 px-4 py-2 rounded-lg bg-red-500/10 border border-red-500/30">
          <p className="text-sm text-red-400 font-mono">
            Error Rate {errorRate}% {'>'} {result.errorThresholdPercent}% Budget
          </p>
        </div>
      )}

      {/* Batch ID & Filename */}
      <p className="text-sm text-slate-400 mb-2 font-mono">
        Batch: <span className="text-white font-bold">{result.batchId.slice(0, 8)}</span>
        {result.filename && (
          <span className="text-slate-600"> • {result.filename}</span>
        )}
      </p>

      {/* Row Counts - Terminal Style */}
      <div className="flex flex-wrap items-center justify-center gap-3 text-sm font-mono mb-4">
        <span className="px-2 py-1 rounded bg-slate-800 text-slate-300">
          Total: <span className="font-bold">{result.rowCountTotal.toLocaleString()}</span>
        </span>
        <span className="px-2 py-1 rounded bg-emerald-500/20 text-emerald-400">
          Inserted: <span className="font-bold">{result.rowCountInserted.toLocaleString()}</span>
        </span>
        {result.rowCountDuplicate > 0 && (
          <span className="px-2 py-1 rounded bg-blue-500/20 text-blue-400">
            Dupes: <span className="font-bold">{result.rowCountDuplicate.toLocaleString()}</span>
          </span>
        )}
        {result.rowCountInvalid > 0 && (
          <span className="px-2 py-1 rounded bg-red-500/20 text-red-400">
            Errors: <span className="font-bold">{result.rowCountInvalid.toLocaleString()}</span>
          </span>
        )}
      </div>

      {/* Processing Metrics */}
      {(result.parseDurationMs !== null || result.dbDurationMs !== null) && (
        <ProcessingMetrics result={result} />
      )}

      {/* Error Table */}
      {result.errors.length > 0 && (
        <ErrorTable
          errors={result.errors}
          totalErrors={result.rowCountInvalid}
          filename={result.filename || 'batch'}
        />
      )}

      {/* Reset Button */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onReset();
        }}
        className="mt-6 px-4 py-2 rounded-md bg-slate-800 text-slate-300 text-sm font-mono hover:bg-slate-700 transition-colors flex items-center gap-2"
      >
        <RefreshCw className="h-4 w-4" />
        Upload Another
      </button>
    </motion.div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const IntakeStation: FC<IntakeStationProps> = ({
  onUploadComplete,
  className,
  disabled = false,
}) => {
  // State
  const [state, setState] = useState<UploadState>('idle');
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [batchResult, setBatchResult] = useState<BatchStatusResult | null>(null);
  const [source, setSource] = useState<DataSourceType>('simplicity');
  const [isDragOver, setIsDragOver] = useState(false);
  const [pollCount, setPollCount] = useState(0);
  const [currentStatus, setCurrentStatus] = useState<string>('');
  const inputRef = useRef<HTMLInputElement>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  // Reset to idle state
  const reset = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    setState('idle');
    setProgress(0);
    setError(null);
    setBatchId(null);
    setBatchResult(null);
    setPollCount(0);
    setCurrentStatus('');
  }, []);

  // Poll for batch status
  const pollBatchStatus = useCallback(
    async (id: string) => {
      const result = await api.getBatchStatus(id);

      if (!result.ok) {
        // Network error during polling - retry unless max attempts
        setPollCount((prev) => {
          if (prev >= MAX_POLL_ATTEMPTS) {
            if (pollIntervalRef.current) {
              clearInterval(pollIntervalRef.current);
              pollIntervalRef.current = null;
            }
            setState('error');
            setError(`Polling timeout after ${MAX_POLL_ATTEMPTS * 2} seconds`);
          }
          return prev + 1;
        });
        return;
      }

      const data = result.data;
      setCurrentStatus(data.status);

      // Check if processing is complete
      if (data.status === 'completed' || data.status === 'failed') {
        // Stop polling
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }

        setBatchResult(data);

        if (data.status === 'completed') {
          // Determine success vs partial
          if (data.rowCountInvalid === 0) {
            setState('success');
          } else {
            setState('partial');
          }
          onUploadComplete?.(id, data);
        } else {
          setState('error');
          setError(data.rejectionReason || data.errorSummary || 'Batch processing failed');
        }
      } else {
        // Still processing - update progress based on status
        const progressMap: Record<string, number> = {
          uploaded: 20,
          staging: 35,
          validating: 50,
          transforming: 65,
          inserting: 80,
          upserting: 85,
        };
        setProgress(progressMap[data.status] ?? 50);
        setPollCount((prev) => prev + 1);
      }
    },
    [onUploadComplete]
  );

  // Start polling for a batch
  const startPolling = useCallback(
    (id: string) => {
      setState('processing');
      setProgress(15);
      setPollCount(0);

      // Initial poll immediately
      pollBatchStatus(id);

      // Then poll every 2 seconds
      pollIntervalRef.current = setInterval(() => {
        pollBatchStatus(id);
      }, POLL_INTERVAL_MS);
    },
    [pollBatchStatus]
  );

  // Upload handler
  const handleUpload = useCallback(
    async (file: File) => {
      if (disabled) return;

      setState('uploading');
      setProgress(5);
      setError(null);
      setBatchId(null);
      setBatchResult(null);

      // Fake progress during upload
      const progressInterval = setInterval(() => {
        setProgress((prev) => Math.min(prev + 2, 12));
      }, 200);

      try {
        const result: BatchUploadResponse = await api.uploadBatch(file, source);

        clearInterval(progressInterval);

        if (result.ok) {
          // Upload successful - now start polling for processing status
          setBatchId(result.data.batchId);
          startPolling(result.data.batchId);
        } else {
          setState('error');
          setProgress(0);
          setError(result.error);
        }
      } catch (err) {
        clearInterval(progressInterval);
        setState('error');
        setProgress(0);
        setError(err instanceof Error ? err.message : 'Upload failed');
      }
    },
    [disabled, source, startPolling]
  );

  // Drag handlers
  const handleDragEnter = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (!disabled) setIsDragOver(true);
    },
    [disabled]
  );

  const handleDragOver = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (!disabled) setIsDragOver(true);
    },
    [disabled]
  );

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
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

      if (disabled) return;

      const files = Array.from(e.dataTransfer.files);
      const csvFile = files.find((f) => f.name.toLowerCase().endsWith('.csv'));

      if (csvFile) {
        await handleUpload(csvFile);
      } else {
        setState('error');
        setError('❌ CSV Parse Failed: Please drop a .csv file');
      }
    },
    [disabled, handleUpload]
  );

  const handleFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        await handleUpload(file);
      }
      e.target.value = '';
    },
    [handleUpload]
  );

  const handleClick = useCallback(() => {
    if (!disabled && state === 'idle') {
      inputRef.current?.click();
    }
  }, [disabled, state]);

  // Derived states
  const isProcessing = state === 'uploading' || state === 'processing';
  const isResult =
    state === 'success' ||
    state === 'partial' ||
    (state === 'error' && batchResult !== null);
  const isUploadError = state === 'error' && batchResult === null;
  const isIdle = state === 'idle';

  return (
    <div className={cn('flex flex-col', className)}>
      {/* Data Source Selector - shown in idle state */}
      {isIdle && !disabled && (
        <DataSourceSelector value={source} onChange={setSource} />
      )}

      {/* Dropzone */}
      <motion.div
        className={cn(
          'relative rounded-xl border-2 border-dashed transition-all duration-300',
          'flex flex-col items-center justify-center py-12 px-6',
          disabled
            ? 'cursor-not-allowed opacity-50'
            : isIdle
            ? 'cursor-pointer'
            : 'cursor-default',
          // Drag over glow effect
          isDragOver &&
            !disabled &&
            'border-emerald-400 bg-emerald-500/10 shadow-[0_0_40px_rgba(16,185,129,0.3)]',
          // Normal states
          !isDragOver &&
            isIdle &&
            'border-slate-700 bg-slate-900/50 hover:border-slate-600 hover:bg-slate-900/80',
          isProcessing && 'border-blue-500/50 bg-blue-500/5',
          state === 'success' && 'border-emerald-500/50 bg-emerald-500/5',
          state === 'partial' && 'border-amber-500/50 bg-amber-500/5',
          state === 'error' && 'border-red-500/50 bg-red-500/5'
        )}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        animate={{ scale: isDragOver && !disabled ? 1.02 : 1 }}
        transition={{ type: 'spring', stiffness: 300, damping: 20 }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv"
          onChange={handleFileSelect}
          className="hidden"
          disabled={disabled}
        />

        <AnimatePresence mode="wait">
          {/* Disabled State */}
          {disabled && (
            <motion.div
              key="disabled"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center text-center"
            >
              <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-slate-800/80 mb-4">
                <AlertTriangle className="h-8 w-8 text-amber-400" />
              </div>
              <h3 className="text-lg font-semibold text-amber-400 mb-1 font-mono">
                Backend Disconnected
              </h3>
              <p className="text-sm text-slate-500">Check Railway deployment status</p>
            </motion.div>
          )}

          {/* Idle State */}
          {isIdle && !isDragOver && !disabled && (
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
          {isDragOver && !disabled && (
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
              <h3 className="text-xl font-bold text-emerald-400 font-mono">Release to Upload</h3>
            </motion.div>
          )}

          {/* Processing State (Uploading + Polling) */}
          {isProcessing && (
            <motion.div
              key="processing"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center text-center w-full max-w-md"
            >
              <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-blue-500/20 mb-4">
                <Loader2 className="h-8 w-8 text-blue-400 animate-spin" />
              </div>
              <h3 className="text-lg font-semibold text-white mb-2 font-mono">
                {state === 'uploading' ? 'Uploading...' : 'Processing...'}
              </h3>

              {/* Status text with current stage */}
              {state === 'processing' && batchId && (
                <div className="flex flex-col items-center gap-1 mb-2">
                  <p className="text-sm text-slate-400 font-mono">
                    Batch {batchId.slice(0, 8)} • Poll #{pollCount}
                  </p>
                  {currentStatus && (
                    <span className="px-2 py-1 rounded bg-blue-500/20 text-blue-400 text-xs font-mono uppercase">
                      {currentStatus}
                    </span>
                  )}
                </div>
              )}

              {/* Progress Bar */}
              <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden mb-2">
                <motion.div
                  className="h-full bg-gradient-to-r from-blue-500 to-emerald-500"
                  initial={{ width: '0%' }}
                  animate={{ width: `${progress}%` }}
                  transition={{ duration: 0.3 }}
                />
              </div>
              <p className="text-sm text-slate-500 font-mono">{progress}%</p>
            </motion.div>
          )}

          {/* Result State (Success, Partial, or Failed with result) */}
          {isResult && batchResult && <ResultSummary result={batchResult} onReset={reset} />}

          {/* Upload Error State (no batch result) */}
          {isUploadError && (
            <motion.div
              key="upload-error"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center text-center"
            >
              <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-red-500/20 mb-4">
                <XCircle className="h-8 w-8 text-red-400" />
              </div>
              <h3 className="text-lg font-semibold text-red-400 mb-2 font-mono">Upload Failed</h3>
              <p className="text-sm text-slate-400 mb-4 max-w-sm">
                {error || 'An unknown error occurred'}
              </p>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  reset();
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

export default IntakeStation;
