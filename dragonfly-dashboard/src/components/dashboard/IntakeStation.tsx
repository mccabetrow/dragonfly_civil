/**
 * IntakeStation Component - Hedge Fund Mode File Dropzone
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * A polished, dark-mode drag-and-drop file upload component for CSV intake.
 * Designed for the Dragonfly "Go-Live" dashboard with billion-dollar aesthetics.
 *
 * Features:
 *   - Animated dropzone with glow effects
 *   - Real-time progress bar during upload
 *   - Green checkmark on success with batch ID
 *   - Error state with user-friendly messages
 *   - Data source selector (Simplicity, JBI, FOIL, Manual)
 *   - Graceful empty/loading states
 *
 * Usage:
 *   <IntakeStation onUploadComplete={(batchId) => refetch()} />
 */

import { type FC, useCallback, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload,
  FileUp,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertTriangle,
} from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import { api, type DataSourceType, type BatchUploadResponse } from '../../lib/api';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface IntakeStationProps {
  /**
   * Called when a batch is successfully uploaded.
   * Use this to invalidate cache or refetch batch history.
   */
  onUploadComplete?: (batchId: string) => void;

  /**
   * Optional className for the container.
   */
  className?: string;

  /**
   * Disable uploads (e.g., when backend is disconnected).
   */
  disabled?: boolean;
}

type UploadState = 'idle' | 'uploading' | 'processing' | 'success' | 'error';

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
  const [source, setSource] = useState<DataSourceType>('simplicity');
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset to idle state
  const reset = useCallback(() => {
    setState('idle');
    setProgress(0);
    setError(null);
    setBatchId(null);
  }, []);

  // Upload handler
  const handleUpload = useCallback(async (file: File) => {
    if (disabled) return;

    setState('uploading');
    setProgress(10);
    setError(null);
    setBatchId(null);

    // Simulate progress during upload
    const progressInterval = setInterval(() => {
      setProgress((prev) => Math.min(prev + 10, 80));
    }, 200);

    try {
      const result: BatchUploadResponse = await api.uploadBatch(file, source);

      clearInterval(progressInterval);

      if (result.ok) {
        setState('success');
        setProgress(100);
        setBatchId(result.data.batchId);
        onUploadComplete?.(result.data.batchId);
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
  }, [disabled, source, onUploadComplete]);

  // Drag handlers
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled) setIsDragOver(true);
  }, [disabled]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled) setIsDragOver(true);
  }, [disabled]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const relatedTarget = e.relatedTarget as HTMLElement;
    if (!relatedTarget || !e.currentTarget.contains(relatedTarget)) {
      setIsDragOver(false);
    }
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
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
  }, [disabled, handleUpload]);

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      await handleUpload(file);
    }
    e.target.value = '';
  }, [handleUpload]);

  const handleClick = useCallback(() => {
    if (!disabled && (state === 'idle' || state === 'error')) {
      inputRef.current?.click();
    }
  }, [disabled, state]);

  // Derived states
  const isUploading = state === 'uploading' || state === 'processing';
  const isSuccess = state === 'success';
  const isError = state === 'error';
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
          disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
          // Drag over glow effect
          isDragOver && !disabled && 'border-emerald-400 bg-emerald-500/10 shadow-[0_0_40px_rgba(16,185,129,0.3)]',
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
              <p className="text-sm text-slate-500">
                Check Railway deployment status
              </p>
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
                {state === 'uploading' ? 'Uploading...' : 'Processing...'}
              </h3>
              
              {/* Progress Bar */}
              <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden mb-2">
                <motion.div
                  className="h-full bg-blue-500"
                  initial={{ width: '0%' }}
                  animate={{ width: `${progress}%` }}
                  transition={{ duration: 0.3 }}
                />
              </div>
              <p className="text-sm text-slate-500 font-mono">{progress}%</p>
            </motion.div>
          )}

          {/* Success State */}
          {isSuccess && batchId && (
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
                ✅ Sent to Processing
              </h3>
              <p className="text-sm text-slate-400 mb-4 font-mono">
                Batch <span className="text-white font-bold">{batchId.slice(0, 8)}</span> queued for intake
              </p>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  reset();
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
