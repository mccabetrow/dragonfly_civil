/**
 * DataIntegrityPage - "Vault Status" dashboard for data integrity
 *
 * Layout:
 * - Top: Hero stats - Total Rows Ingested, Integrity Score, Failed Count
 * - Middle: Batch Integrity Vault (Green/Red status per batch)
 * - Bottom: Failed Rows table (Dead Letter Queue) with retry/ignore actions
 * - Click → Expand → Edit/Retry functionality
 *
 * Business purpose: Absolute proof that every row ingested from Simplicity
 * or FOIL is stored perfectly. Dead Letter Queue to fix failed rows manually.
 */
import React, { useState, useCallback, type FC } from 'react';
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  RefreshCw,
  CheckCircle,
  XCircle,
  Clock,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  EyeOff,
  Database,
  FileWarning,
  Vault,
  FileCheck,
} from 'lucide-react';
import PageHeader from '../components/ui/PageHeader';
import { cn } from '../lib/design-tokens';
import { useToast } from '../components/ui/Toast';
import {
  useIntegrityDashboard,
  useFailedRows,
  useBatchIntegrityList,
  checkBatchIntegrity,
  retryFailedRow,
  ignoreFailedRow,
  type FailedRow,
  type BatchIntegrity,
} from '../hooks/useDataIntegrity';

// ═══════════════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

function formatNumber(n: number): string {
  return new Intl.NumberFormat('en-US').format(n);
}

function formatPercent(n: number): string {
  return `${n.toFixed(3)}%`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  try {
    return new Date(dateStr).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

function getStatusBadge(status: FailedRow['resolution_status']) {
  const config = {
    pending: {
      bg: 'bg-amber-50',
      text: 'text-amber-700',
      border: 'border-amber-200',
      icon: Clock,
      label: 'Pending',
    },
    resolved: {
      bg: 'bg-emerald-50',
      text: 'text-emerald-700',
      border: 'border-emerald-200',
      icon: CheckCircle,
      label: 'Resolved',
    },
    ignored: {
      bg: 'bg-gray-50',
      text: 'text-gray-600',
      border: 'border-gray-200',
      icon: EyeOff,
      label: 'Ignored',
    },
    retry_scheduled: {
      bg: 'bg-blue-50',
      text: 'text-blue-700',
      border: 'border-blue-200',
      icon: RotateCcw,
      label: 'Retrying',
    },
  };
  return config[status] || config.pending;
}

// ═══════════════════════════════════════════════════════════════════════════
// HERO STAT CARD
// ═══════════════════════════════════════════════════════════════════════════

interface HeroStatProps {
  label: string;
  value: string;
  icon: React.ReactNode;
  colorClass?: string;
  loading?: boolean;
}

const HeroStat: FC<HeroStatProps> = ({ label, value, icon, colorClass = 'text-gray-900', loading }) => (
  <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
    <div className="flex items-center gap-3 mb-3">
      <div className="p-2 bg-gray-50 rounded-lg text-gray-600">{icon}</div>
      <span className="text-sm font-medium text-gray-500">{label}</span>
    </div>
    <div className={cn('text-3xl font-bold', colorClass)}>
      {loading ? <div className="h-9 w-24 bg-gray-100 rounded animate-pulse" /> : value}
    </div>
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// VAULT STATUS CARD (Integrity Score)
// ═══════════════════════════════════════════════════════════════════════════

interface VaultStatusCardProps {
  score: number;
  loading: boolean;
}

const VaultStatusCard: FC<VaultStatusCardProps> = ({ score, loading }) => {
  const isPerfect = score >= 99.999;
  const isGood = score >= 99.9;
  const Icon = isPerfect ? ShieldCheck : isGood ? Shield : ShieldAlert;
  const bgGradient = isPerfect
    ? 'from-emerald-500 to-emerald-700'
    : isGood
      ? 'from-blue-500 to-blue-700'
      : 'from-amber-500 to-amber-700';

  return (
    <div
      className={cn('bg-gradient-to-br rounded-xl p-6 text-white shadow-lg', bgGradient)}
    >
      <div className="flex items-center gap-3 mb-2">
        <div className="p-2 bg-white/20 rounded-lg">
          <Icon className="w-6 h-6" />
        </div>
        <span className="text-white/80 text-sm font-medium">Vault Integrity Score</span>
      </div>
      <div className="text-4xl font-bold">
        {loading ? (
          <div className="h-10 w-32 bg-white/20 rounded animate-pulse" />
        ) : (
          formatPercent(score)
        )}
      </div>
      <div className="mt-2 text-sm text-white/70">
        {isPerfect ? 'Perfect integrity' : isGood ? 'Minor discrepancies' : 'Review needed'}
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// FAILED ROW ITEM (Expandable)
// ═══════════════════════════════════════════════════════════════════════════

interface FailedRowItemProps {
  row: FailedRow;
  isExpanded: boolean;
  onToggle: () => void;
  onRetry: () => Promise<void>;
  onIgnore: () => Promise<void>;
  isRetrying: boolean;
}

const FailedRowItem: FC<FailedRowItemProps> = ({
  row,
  isExpanded,
  onToggle,
  onRetry,
  onIgnore,
  isRetrying,
}) => {
  const statusConfig = getStatusBadge(row.resolution_status);
  const StatusIcon = statusConfig.icon;

  return (
    <div className="border border-gray-200 rounded-lg bg-white overflow-hidden">
      {/* Header Row (clickable) */}
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-center gap-4 hover:bg-gray-50 transition-colors text-left"
      >
        <div className="flex-shrink-0">
          {isExpanded ? (
            <ChevronUp className="w-4 h-4 text-gray-400" />
          ) : (
            <ChevronDown className="w-4 h-4 text-gray-400" />
          )}
        </div>

        <div className="flex-shrink-0 w-20">
          <span className="text-sm font-mono text-gray-500">Row #{row.row_index}</span>
        </div>

        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-gray-900 truncate">
            {row.error_message || row.discrepancy_type}
          </div>
          <div className="text-xs text-gray-500 truncate">
            Batch: {row.batch_name || row.batch_id.slice(0, 8)}
          </div>
        </div>

        <div className="flex-shrink-0">
          <span
            className={cn(
              'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
              statusConfig.bg,
              statusConfig.text,
              statusConfig.border
            )}
          >
            <StatusIcon className="w-3 h-3" />
            {statusConfig.label}
          </span>
        </div>

        <div className="flex-shrink-0 w-32 text-right">
          <span className="text-xs text-gray-500">{formatDate(row.created_at)}</span>
        </div>
      </button>

      {/* Expanded Details */}
      {isExpanded && (
        <div className="border-t border-gray-100 px-4 py-4 bg-gray-50">
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <h4 className="text-xs font-semibold text-gray-500 uppercase mb-1">
                Discrepancy Type
              </h4>
              <p className="text-sm text-gray-900">{row.discrepancy_type}</p>
            </div>
            <div>
              <h4 className="text-xs font-semibold text-gray-500 uppercase mb-1">Retry Count</h4>
              <p className="text-sm text-gray-900">{row.retry_count}</p>
            </div>
            <div className="col-span-2">
              <h4 className="text-xs font-semibold text-gray-500 uppercase mb-1">Error Message</h4>
              <p className="bg-rose-50 text-rose-800 rounded px-2 py-1 font-mono text-xs">
                {row.error_message || 'No error message'}
              </p>
            </div>
            {row.raw_data && (
              <div className="col-span-2">
                <h4 className="text-xs font-semibold text-gray-500 uppercase mb-1">Raw Data</h4>
                <pre className="text-xs bg-gray-100 rounded p-2 overflow-x-auto max-h-40">
                  {JSON.stringify(row.raw_data, null, 2)}
                </pre>
              </div>
            )}
            {row.resolution_notes && (
              <div className="col-span-2">
                <h4 className="text-xs font-semibold text-gray-500 uppercase mb-1">
                  Resolution Notes
                </h4>
                <p className="text-sm text-gray-700">{row.resolution_notes}</p>
              </div>
            )}
          </div>

          {/* Action Buttons */}
          {row.resolution_status === 'pending' && (
            <div className="flex items-center gap-3 pt-3 border-t border-gray-200">
              <button
                onClick={onRetry}
                disabled={isRetrying}
                className={cn(
                  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
                  'bg-blue-600 text-white hover:bg-blue-700',
                  'disabled:opacity-50 disabled:cursor-not-allowed'
                )}
              >
                {isRetrying ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <RotateCcw className="w-4 h-4" />
                )}
                Retry Import
              </button>
              <button
                onClick={onIgnore}
                disabled={isRetrying}
                className={cn(
                  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
                  'bg-gray-100 text-gray-700 hover:bg-gray-200',
                  'disabled:opacity-50 disabled:cursor-not-allowed'
                )}
              >
                <EyeOff className="w-4 h-4" />
                Ignore
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// PAGINATION
// ═══════════════════════════════════════════════════════════════════════════

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  hasNext: boolean;
  hasPrev: boolean;
  onNext: () => void;
  onPrev: () => void;
}

const Pagination: FC<PaginationProps> = ({
  currentPage,
  totalPages,
  hasNext,
  hasPrev,
  onNext,
  onPrev,
}) => (
  <div className="flex items-center justify-between border-t border-gray-200 bg-gray-50 px-4 py-3 rounded-b-lg">
    <span className="text-sm text-gray-600">
      Page {currentPage} of {totalPages || 1}
    </span>
    <div className="flex gap-2">
      <button
        onClick={onPrev}
        disabled={!hasPrev}
        className="p-1.5 rounded border border-gray-200 bg-white disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>
      <button
        onClick={onNext}
        disabled={!hasNext}
        className="p-1.5 rounded border border-gray-200 bg-white disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
      >
        <ChevronRight className="w-4 h-4" />
      </button>
    </div>
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// BATCH INTEGRITY VAULT
// ═══════════════════════════════════════════════════════════════════════════

const BatchIntegrityVault: FC = () => {
  const { addToast } = useToast();
  const {
    batches,
    loading,
    error,
    refetch,
  } = useBatchIntegrityList({ limit: 10 });

  const [verifyingBatchId, setVerifyingBatchId] = useState<string | null>(null);

  const handleVerify = useCallback(
    async (batchId: string) => {
      setVerifyingBatchId(batchId);
      try {
        const result = await checkBatchIntegrity(batchId);
        if (result.is_verified) {
          addToast({
            variant: 'success',
            title: 'Batch Verified',
            description: `Batch integrity confirmed: ${result.db_row_count}/${result.csv_row_count} rows stored`,
          });
        } else {
          addToast({
            variant: 'warning',
            title: 'Discrepancy Detected',
            description: `Expected ${result.csv_row_count} rows, found ${result.db_row_count}`,
          });
        }
        await refetch();
      } catch (err) {
        addToast({
          variant: 'error',
          title: 'Verification Failed',
          description: err instanceof Error ? err.message : 'Unknown error',
        });
      } finally {
        setVerifyingBatchId(null);
      }
    },
    [addToast, refetch]
  );

  const getStatusBadge = (status: BatchIntegrity['integrity_status']) => {
    switch (status) {
      case 'verified':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-full bg-emerald-100 text-emerald-700">
            <CheckCircle className="w-3.5 h-3.5" />
            Verified
          </span>
        );
      case 'discrepancy':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-full bg-rose-100 text-rose-700">
            <XCircle className="w-3.5 h-3.5" />
            Discrepancy
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-full bg-gray-100 text-gray-600">
            <FileCheck className="w-3.5 h-3.5" />
            Pending
          </span>
        );
    }
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-4 py-4 border-b border-gray-200 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-50 rounded-lg">
            <Vault className="w-5 h-5 text-indigo-600" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Batch Integrity Vault</h2>
            <p className="text-sm text-gray-500">
              Mathematical verification that no data is lost during ingestion
            </p>
          </div>
        </div>
        <button
          onClick={() => refetch()}
          disabled={loading}
          className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
          title="Refresh"
        >
          <RefreshCw className={`w-4 h-4 text-gray-500 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {loading && batches.length === 0 ? (
        <div className="p-8 flex items-center justify-center">
          <RefreshCw className="w-6 h-6 text-gray-400 animate-spin" />
        </div>
      ) : error ? (
        <div className="p-8 text-center">
          <XCircle className="w-10 h-10 text-rose-400 mx-auto mb-3" />
          <p className="text-sm text-gray-600">{error.message}</p>
        </div>
      ) : batches.length === 0 ? (
        <div className="p-12 text-center">
          <Vault className="w-12 h-12 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-1">No Batches Yet</h3>
          <p className="text-sm text-gray-500">
            Imported batches will appear here for integrity verification.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Batch
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Source File
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  CSV Rows
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  DB Rows
                </th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Score
                </th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Action
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {batches.map((batch) => (
                <tr key={batch.batch_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span className="text-sm font-mono text-gray-900">
                      {batch.batch_id.slice(0, 8)}…
                    </span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span className="text-sm text-gray-700">
                      {batch.filename || '—'}
                    </span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-right">
                    <span className="text-sm font-medium text-gray-900">
                      {batch.csv_row_count.toLocaleString()}
                    </span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-right">
                    <span
                      className={`text-sm font-medium ${
                        batch.db_row_count < batch.csv_row_count
                          ? 'text-amber-600'
                          : 'text-gray-900'
                      }`}
                    >
                      {batch.db_row_count.toLocaleString()}
                    </span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-center">
                    <span
                      className={`text-sm font-semibold ${
                        batch.integrity_score >= 100
                          ? 'text-emerald-600'
                          : batch.integrity_score >= 95
                          ? 'text-amber-600'
                          : 'text-rose-600'
                      }`}
                    >
                      {batch.integrity_score.toFixed(1)}%
                    </span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-center">
                    {getStatusBadge(batch.integrity_status)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-center">
                    <button
                      onClick={() => handleVerify(batch.batch_id)}
                      disabled={verifyingBatchId === batch.batch_id || batch.integrity_status === 'verified'}
                      className={`inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                        batch.integrity_status === 'verified'
                          ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                          : 'bg-indigo-50 text-indigo-700 hover:bg-indigo-100'
                      }`}
                    >
                      {verifyingBatchId === batch.batch_id ? (
                        <>
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                          Verifying…
                        </>
                      ) : (
                        <>
                          <FileCheck className="w-3.5 h-3.5" />
                          Verify
                        </>
                      )}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// MAIN PAGE COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export function DataIntegrityPage() {
  const { addToast } = useToast();
  const dashboard = useIntegrityDashboard();
  const failedRows = useFailedRows({ limit: 20, status: 'pending' });

  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);
  const [retryingRowId, setRetryingRowId] = useState<string | null>(null);

  const handleToggleExpand = useCallback((rowId: string) => {
    setExpandedRowId((prev) => (prev === rowId ? null : rowId));
  }, []);

  const handleRetry = useCallback(
    async (row: FailedRow) => {
      setRetryingRowId(row.id);
      try {
        const result = await retryFailedRow(row.id);
        if (result.success) {
          addToast({
            variant: 'success',
            title: 'Retry scheduled',
            description: `Row #${row.row_index} will be re-processed`,
          });
          await failedRows.refetch();
          await dashboard.refetch();
        } else {
          addToast({
            variant: 'error',
            title: 'Retry failed',
            description: result.message,
          });
        }
      } catch (err) {
        addToast({
          variant: 'error',
          title: 'Retry failed',
          description: err instanceof Error ? err.message : 'Unknown error',
        });
      } finally {
        setRetryingRowId(null);
      }
    },
    [addToast, failedRows, dashboard]
  );

  const handleIgnore = useCallback(
    async (row: FailedRow) => {
      setRetryingRowId(row.id);
      try {
        await ignoreFailedRow(row.id);
        addToast({
          variant: 'info',
          title: 'Row dismissed',
          description: `Row #${row.row_index} marked as dismissed`,
        });
        await failedRows.refetch();
        await dashboard.refetch();
      } catch (err) {
        addToast({
          variant: 'error',
          title: 'Action failed',
          description: err instanceof Error ? err.message : 'Unknown error',
        });
      } finally {
        setRetryingRowId(null);
      }
    },
    [addToast, failedRows, dashboard]
  );

  const isLoading = dashboard.loading;
  const stats = dashboard.data;

  return (
    <div className="min-h-screen bg-gray-50">
      <PageHeader
        title="Data Integrity"
        description="Vault status and failed row recovery"
        badge={<Shield className="w-5 h-5 text-emerald-600" />}
        actions={
          <button
            onClick={() => {
              dashboard.refetch();
              failedRows.refetch();
            }}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-gray-200 text-gray-700 text-sm font-medium hover:bg-gray-50"
          >
            <RefreshCw className={cn('w-4 h-4', isLoading && 'animate-spin')} />
            Refresh
          </button>
        }
      />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* ═══════════════════════════════════════════════════════════════════ */}
        {/* HERO STATS ROW */}
        {/* ═══════════════════════════════════════════════════════════════════ */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <VaultStatusCard score={stats?.integrity_score_pct ?? 100} loading={isLoading} />

          <HeroStat
            label="Total Rows Ingested"
            value={formatNumber(stats?.total_rows_ingested ?? 0)}
            icon={<Database className="w-5 h-5" />}
            loading={isLoading}
          />

          <HeroStat
            label="Successfully Stored"
            value={formatNumber(stats?.rows_successfully_stored ?? 0)}
            icon={<CheckCircle className="w-5 h-5" />}
            colorClass="text-emerald-600"
            loading={isLoading}
          />

          <HeroStat
            label="Failed Rows"
            value={formatNumber(stats?.pending_resolution ?? 0)}
            icon={<FileWarning className="w-5 h-5" />}
            colorClass={
              (stats?.pending_resolution ?? 0) > 0 ? 'text-rose-600' : 'text-gray-600'
            }
            loading={isLoading}
          />
        </div>

        {/* ═══════════════════════════════════════════════════════════════════ */}
        {/* SECONDARY STATS */}
        {/* ═══════════════════════════════════════════════════════════════════ */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-sm text-gray-500 mb-1">Batches Processed</div>
            <div className="text-xl font-semibold text-gray-900">
              {isLoading ? '—' : formatNumber(stats?.batches_processed ?? 0)}
            </div>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-sm text-gray-500 mb-1">Batches with Issues</div>
            <div className="text-xl font-semibold text-amber-600">
              {isLoading ? '—' : formatNumber(stats?.batches_with_issues ?? 0)}
            </div>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-sm text-gray-500 mb-1">Resolved</div>
            <div className="text-xl font-semibold text-emerald-600">
              {isLoading ? '—' : formatNumber(stats?.resolved_count ?? 0)}
            </div>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-sm text-gray-500 mb-1">Last Check</div>
            <div className="text-sm font-medium text-gray-700">
              {isLoading ? '—' : formatDate(stats?.last_check_at ?? null)}
            </div>
          </div>
        </div>

        {/* ═══════════════════════════════════════════════════════════════════ */}
        {/* BATCH INTEGRITY VAULT */}
        {/* ═══════════════════════════════════════════════════════════════════ */}
        <BatchIntegrityVault />

        {/* ═══════════════════════════════════════════════════════════════════ */}
        {/* FAILED ROWS (DEAD LETTER QUEUE) */}
        {/* ═══════════════════════════════════════════════════════════════════ */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-4 py-4 border-b border-gray-200 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-amber-50 rounded-lg">
                <AlertTriangle className="w-5 h-5 text-amber-600" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Dead Letter Queue</h2>
                <p className="text-sm text-gray-500">
                  {failedRows.total} failed row{failedRows.total !== 1 ? 's' : ''} pending
                  resolution
                </p>
              </div>
            </div>
          </div>

          {/* Failed Rows List */}
          {failedRows.loading ? (
            <div className="p-8 flex items-center justify-center">
              <RefreshCw className="w-6 h-6 text-gray-400 animate-spin" />
            </div>
          ) : failedRows.rows.length === 0 ? (
            <div className="p-12 text-center">
              <ShieldCheck className="w-12 h-12 text-emerald-400 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-gray-900 mb-1">All Clear</h3>
              <p className="text-sm text-gray-500">
                No pending discrepancies. All ingested rows are stored correctly.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {failedRows.rows.map((row) => (
                <FailedRowItem
                  key={row.id}
                  row={row}
                  isExpanded={expandedRowId === row.id}
                  onToggle={() => handleToggleExpand(row.id)}
                  onRetry={() => handleRetry(row)}
                  onIgnore={() => handleIgnore(row)}
                  isRetrying={retryingRowId === row.id}
                />
              ))}
            </div>
          )}

          {/* Pagination */}
          {failedRows.rows.length > 0 && (
            <Pagination
              currentPage={failedRows.pagination.currentPage}
              totalPages={failedRows.pagination.totalPages}
              hasNext={failedRows.pagination.hasNext}
              hasPrev={failedRows.pagination.hasPrev}
              onNext={failedRows.pagination.nextPage}
              onPrev={failedRows.pagination.prevPage}
            />
          )}
        </div>

        {/* ═══════════════════════════════════════════════════════════════════ */}
        {/* ERROR STATE */}
        {/* ═══════════════════════════════════════════════════════════════════ */}
        {(dashboard.error || failedRows.error) && (
          <div className="bg-rose-50 border border-rose-200 rounded-lg p-4 flex items-start gap-3">
            <XCircle className="w-5 h-5 text-rose-600 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="text-sm font-medium text-rose-900">Error Loading Data</h3>
              <p className="text-sm text-rose-700 mt-1">
                {dashboard.error?.message || failedRows.error?.message || 'Unknown error'}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default DataIntegrityPage;
