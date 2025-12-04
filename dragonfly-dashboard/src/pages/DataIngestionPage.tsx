/**
 * DataIngestionPage - Enterprise CSV upload and batch management
 *
 * Layout:
 * - Left column: Upload card with drag-and-drop
 * - Right column: Recent batches table
 * - Bottom: Batch detail drawer/panel
 */
import { type FC, useState, useCallback, useRef, type DragEvent } from 'react';
import {
  Upload,
  FileText,
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  AlertTriangle,
  ChevronRight,
  X,
  RefreshCw,
  Database,
} from 'lucide-react';
import PageHeader from '../components/ui/PageHeader';
import { cn } from '../lib/design-tokens';
import { useToast } from '../components/ui/Toast';
import {
  useIngestBatches,
  useBatchDetail,
  uploadSimplicityCSV,
  type IngestBatch,
  type IngestApiError,
} from '../hooks/useIngestBatches';

// ═══════════════════════════════════════════════════════════════════════════
// STATUS BADGE
// ═══════════════════════════════════════════════════════════════════════════

interface StatusBadgeProps {
  status: IngestBatch['status'];
}

const StatusBadge: FC<StatusBadgeProps> = ({ status }) => {
  const config = {
    pending: {
      bg: 'bg-amber-50',
      text: 'text-amber-700',
      border: 'border-amber-200',
      icon: Clock,
      label: 'Pending',
    },
    processing: {
      bg: 'bg-blue-50',
      text: 'text-blue-700',
      border: 'border-blue-200',
      icon: Loader2,
      label: 'Processing',
    },
    completed: {
      bg: 'bg-emerald-50',
      text: 'text-emerald-700',
      border: 'border-emerald-200',
      icon: CheckCircle,
      label: 'Completed',
    },
    failed: {
      bg: 'bg-rose-50',
      text: 'text-rose-700',
      border: 'border-rose-200',
      icon: XCircle,
      label: 'Failed',
    },
  }[status];

  const Icon = config.icon;

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold',
        config.bg,
        config.text,
        config.border
      )}
    >
      <Icon className={cn('h-3.5 w-3.5', status === 'processing' && 'animate-spin')} />
      {config.label}
    </span>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// UPLOAD CARD
// ═══════════════════════════════════════════════════════════════════════════

interface UploadCardProps {
  onUploadComplete: () => void;
}

const UploadCard: FC<UploadCardProps> = ({ onUploadComplete }) => {
  const { addToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    setUploadError(null);

    const files = e.dataTransfer.files;
    if (files.length > 0) {
      const file = files[0];
      if (file.name.toLowerCase().endsWith('.csv')) {
        setSelectedFile(file);
      } else {
        setUploadError('Please select a CSV file');
      }
    }
  }, []);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setUploadError(null);
    const files = e.target.files;
    if (files && files.length > 0) {
      const file = files[0];
      if (file.name.toLowerCase().endsWith('.csv')) {
        setSelectedFile(file);
      } else {
        setUploadError('Please select a CSV file');
      }
    }
  }, []);

  const handleUpload = useCallback(async () => {
    if (!selectedFile) return;

    setIsUploading(true);
    setUploadError(null);

    try {
      const result = await uploadSimplicityCSV(selectedFile);

      addToast({
        variant: 'success',
        title: 'Upload Complete',
        description: `${result.filename}: ${result.row_count_valid} valid, ${result.row_count_invalid} invalid (batch ${result.batch_id.slice(0, 8)}...)`,
      });

      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      onUploadComplete();
    } catch (err) {
      const apiError = err as IngestApiError;

      if (apiError.isAuthError) {
        setUploadError('API key misconfigured – contact admin');
        addToast({
          variant: 'error',
          title: 'Authentication Failed',
          description: 'API key misconfigured – contact admin',
        });
      } else {
        setUploadError(apiError.message || 'Upload failed');
        addToast({
          variant: 'error',
          title: 'Upload Failed',
          description: apiError.message || 'An unknown error occurred',
        });
      }
    } finally {
      setIsUploading(false);
    }
  }, [selectedFile, addToast, onUploadComplete]);

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        <Upload className="h-5 w-5 text-slate-400" />
        <h3 className="font-semibold text-slate-900">Upload CSV</h3>
      </div>

      {/* Drag-and-drop area */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          'relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 transition-all duration-200',
          isDragging
            ? 'border-indigo-400 bg-indigo-50'
            : 'border-slate-200 bg-slate-50 hover:border-slate-300 hover:bg-slate-100'
        )}
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-indigo-100">
          <Upload className="h-6 w-6 text-indigo-600" />
        </div>
        <p className="mt-3 text-sm font-medium text-slate-700">
          Drag and drop your Simplicity CSV here
        </p>
        <p className="mt-1 text-xs text-slate-500">or click to browse</p>

        <input
          ref={fileInputRef}
          type="file"
          accept=".csv"
          onChange={handleFileSelect}
          className="absolute inset-0 cursor-pointer opacity-0"
        />
      </div>

      {/* Selected file display */}
      {selectedFile && (
        <div className="mt-4 flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="flex items-center gap-3">
            <FileText className="h-5 w-5 text-indigo-600" />
            <div>
              <p className="text-sm font-medium text-slate-900">{selectedFile.name}</p>
              <p className="text-xs text-slate-500">{formatFileSize(selectedFile.size)}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              setSelectedFile(null);
              if (fileInputRef.current) fileInputRef.current.value = '';
            }}
            className="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Error display */}
      {uploadError && (
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
          <p className="text-sm text-rose-700">{uploadError}</p>
        </div>
      )}

      {/* Upload button */}
      <button
        type="button"
        disabled={!selectedFile || isUploading}
        onClick={handleUpload}
        className={cn(
          'mt-4 flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition-all',
          selectedFile && !isUploading
            ? 'bg-indigo-600 text-white hover:bg-indigo-700'
            : 'cursor-not-allowed bg-slate-100 text-slate-400'
        )}
      >
        {isUploading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Uploading...
          </>
        ) : (
          <>
            <Upload className="h-4 w-4" />
            Upload & Process
          </>
        )}
      </button>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// BATCHES TABLE
// ═══════════════════════════════════════════════════════════════════════════

interface BatchesTableProps {
  batches: IngestBatch[];
  loading: boolean;
  error: IngestApiError | null;
  onSelectBatch: (batch: IngestBatch) => void;
  selectedBatchId: string | null;
  onRefresh: () => void;
}

const BatchesTable: FC<BatchesTableProps> = ({
  batches,
  loading,
  error,
  onSelectBatch,
  selectedBatchId,
  onRefresh,
}) => {
  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return '—';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  };

  if (error?.isAuthError) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 text-rose-600" />
          <div>
            <h3 className="font-semibold text-rose-800">Authentication Error</h3>
            <p className="mt-1 text-sm text-rose-700">
              API key misconfigured – contact admin
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-slate-400" />
          <h3 className="font-semibold text-slate-900">Recent Batches</h3>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100"
        >
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
          Refresh
        </button>
      </div>

      {loading && batches.length === 0 ? (
        <div className="p-6">
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-12 animate-pulse rounded-lg bg-slate-100" />
            ))}
          </div>
        </div>
      ) : batches.length === 0 ? (
        <div className="p-6 text-center">
          <Database className="mx-auto h-8 w-8 text-slate-300" />
          <p className="mt-2 text-sm text-slate-500">No batches yet</p>
          <p className="text-xs text-slate-400">Upload a CSV to get started</p>
        </div>
      ) : (
        <div className="divide-y divide-slate-100">
          {batches.map((batch) => (
            <button
              key={batch.id}
              type="button"
              onClick={() => onSelectBatch(batch)}
              className={cn(
                'flex w-full items-center justify-between px-6 py-3 text-left transition-colors',
                selectedBatchId === batch.id
                  ? 'bg-indigo-50'
                  : 'hover:bg-slate-50'
              )}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-3">
                  <p className="truncate text-sm font-medium text-slate-900">
                    {batch.filename}
                  </p>
                  <StatusBadge status={batch.status} />
                </div>
                <div className="mt-1 flex items-center gap-4 text-xs text-slate-500">
                  <span>{formatDate(batch.created_at)}</span>
                  <span className="text-emerald-600">
                    {batch.row_count_valid} valid
                  </span>
                  {batch.row_count_invalid > 0 && (
                    <span className="text-rose-600">
                      {batch.row_count_invalid} invalid
                    </span>
                  )}
                </div>
              </div>
              <ChevronRight className="h-5 w-5 shrink-0 text-slate-300" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// BATCH DETAIL PANEL
// ═══════════════════════════════════════════════════════════════════════════

interface BatchDetailPanelProps {
  batchId: string | null;
  onClose: () => void;
}

const BatchDetailPanel: FC<BatchDetailPanelProps> = ({ batchId, onClose }) => {
  const { batch, errors, loading, error } = useBatchDetail(batchId);

  if (!batchId) return null;

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return '—';
    const date = new Date(dateStr);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  };

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full max-w-lg overflow-hidden border-l border-slate-200 bg-white shadow-xl sm:w-[480px]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
        <h3 className="font-semibold text-slate-900">Batch Details</h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* Content */}
      <div className="h-full overflow-y-auto pb-24">
        {loading ? (
          <div className="space-y-4 p-6">
            <div className="h-32 animate-pulse rounded-xl bg-slate-100" />
            <div className="h-48 animate-pulse rounded-xl bg-slate-100" />
          </div>
        ) : error ? (
          <div className="p-6">
            <div className="rounded-xl border border-rose-200 bg-rose-50 p-4">
              <p className="text-sm text-rose-700">
                {error.isAuthError
                  ? 'API key misconfigured – contact admin'
                  : error.message}
              </p>
            </div>
          </div>
        ) : batch ? (
          <div className="space-y-6 p-6">
            {/* Summary Card */}
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-900">{batch.filename}</span>
                <StatusBadge status={batch.status} />
              </div>
              <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-slate-500">Source</span>
                  <p className="font-medium text-slate-900">{batch.source}</p>
                </div>
                <div>
                  <span className="text-slate-500">Created</span>
                  <p className="font-medium text-slate-900">{formatDate(batch.created_at)}</p>
                </div>
                <div>
                  <span className="text-slate-500">Processed</span>
                  <p className="font-medium text-slate-900">{formatDate(batch.processed_at)}</p>
                </div>
                <div>
                  <span className="text-slate-500">Created By</span>
                  <p className="font-medium text-slate-900">{batch.created_by || '—'}</p>
                </div>
              </div>

              {/* Counts */}
              <div className="mt-4 grid grid-cols-3 gap-2">
                <div className="rounded-lg bg-white p-3 text-center">
                  <p className="text-2xl font-bold text-slate-900">{batch.row_count_raw}</p>
                  <p className="text-xs text-slate-500">Total Rows</p>
                </div>
                <div className="rounded-lg bg-emerald-50 p-3 text-center">
                  <p className="text-2xl font-bold text-emerald-700">{batch.row_count_valid}</p>
                  <p className="text-xs text-emerald-600">Valid</p>
                </div>
                <div className="rounded-lg bg-rose-50 p-3 text-center">
                  <p className="text-2xl font-bold text-rose-700">{batch.row_count_invalid}</p>
                  <p className="text-xs text-rose-600">Invalid</p>
                </div>
              </div>

              {batch.error_summary && (
                <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3">
                  <p className="text-xs font-medium text-rose-800">Error Summary</p>
                  <p className="mt-1 text-sm text-rose-700">{batch.error_summary}</p>
                </div>
              )}
            </div>

            {/* Invalid Rows Table */}
            {errors.length > 0 && (
              <div>
                <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900">
                  <AlertTriangle className="h-4 w-4 text-rose-500" />
                  Invalid Rows ({errors.length})
                </h4>
                <div className="overflow-x-auto rounded-xl border border-slate-200">
                  <table className="min-w-full divide-y divide-slate-100 text-sm">
                    <thead className="bg-slate-50">
                      <tr>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-slate-600">
                          Row
                        </th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-slate-600">
                          Case #
                        </th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-slate-600">
                          Errors
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 bg-white">
                      {errors.slice(0, 20).map((row, idx) => (
                        <tr key={idx}>
                          <td className="whitespace-nowrap px-3 py-2 text-slate-600">
                            {row.row_index + 1}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 font-medium text-slate-900">
                            {row.case_number || '—'}
                          </td>
                          <td className="px-3 py-2">
                            {row.validation_errors?.map((err, i) => (
                              <p key={i} className="text-xs text-rose-600">
                                {err}
                              </p>
                            )) || '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {errors.length > 20 && (
                  <p className="mt-2 text-center text-xs text-slate-500">
                    Showing first 20 of {errors.length} errors
                  </p>
                )}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════════════════════════

const DataIngestionPage: FC = () => {
  const { batches, loading, error, refetch } = useIngestBatches();
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);

  const handleSelectBatch = useCallback((batch: IngestBatch) => {
    setSelectedBatchId(batch.id);
  }, []);

  const handleCloseBatchDetail = useCallback(() => {
    setSelectedBatchId(null);
  }, []);

  return (
    <div className="relative space-y-6">
      <PageHeader
        title="Data Ingestion"
        description="Upload Simplicity CSV exports and monitor batch processing status."
      />

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Left: Upload Card */}
        <div>
          <UploadCard onUploadComplete={refetch} />
        </div>

        {/* Right: Batches Table */}
        <div>
          <BatchesTable
            batches={batches}
            loading={loading}
            error={error}
            onSelectBatch={handleSelectBatch}
            selectedBatchId={selectedBatchId}
            onRefresh={refetch}
          />
        </div>
      </div>

      {/* Batch Detail Slide-over */}
      {selectedBatchId && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40 bg-black/20"
            onClick={handleCloseBatchDetail}
          />
          <BatchDetailPanel
            batchId={selectedBatchId}
            onClose={handleCloseBatchDetail}
          />
        </>
      )}
    </div>
  );
};

export default DataIngestionPage;
