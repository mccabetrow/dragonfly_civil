import React, { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import RefreshButton from './RefreshButton';
import {
  usePlaintiffWorkbench,
  type PlaintiffWorkbenchRow,
  type PlaintiffStatusCode,
} from '../hooks/usePlaintiffWorkbench';
import { formatCurrency } from '../utils/formatters';
import DemoLockCard from './DemoLockCard';
import { DEFAULT_DEMO_LOCK_MESSAGE } from '../hooks/metricsState';
import SectionHeader from './SectionHeader';

type StatusFilter = 'all' | Exclude<PlaintiffStatusCode, 'unknown'>;

const STATUS_FILTERS: Array<{ value: StatusFilter; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'new', label: 'New' },
  { value: 'contacted', label: 'Contacted' },
  { value: 'qualified', label: 'Qualified' },
  { value: 'sent_agreement', label: 'Sent agreement' },
  { value: 'signed', label: 'Signed' },
  { value: 'lost', label: 'Lost' },
];

const TABLE_SKELETON_ROWS = 5;
const TABLE_COLUMN_COUNT = 7;

export default function PlaintiffWorkbench() {
  const navigate = useNavigate();
  const { state, refetch } = usePlaintiffWorkbench();
  const { status, data, errorMessage, lockMessage } = state;
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [searchTerm, setSearchTerm] = useState('');

  const isLoading = status === 'idle' || status === 'loading';
  const isDemoLocked = status === 'demo_locked';
  const rows = data ?? [];

  const handleRefresh = useCallback(() => refetch(), [refetch]);
  const handleSearch = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    setSearchTerm(event.target.value);
  }, []);

  const filteredRows = useMemo(() => {
    if (rows.length === 0) {
      return [];
    }
    const normalizedSearch = searchTerm.trim().toLowerCase();
    return rows.filter((row) => {
      const matchesStatus = statusFilter === 'all' ? true : row.status === statusFilter;
      if (!normalizedSearch) {
        return matchesStatus;
      }
      const haystack = `${row.plaintiffName} ${row.firmName}`.toLowerCase();
      return matchesStatus && haystack.includes(normalizedSearch);
    });
  }, [rows, statusFilter, searchTerm]);

  const hasRows = filteredRows.length > 0;
  const showSkeleton = isLoading && rows.length === 0;
  const displayError = !isDemoLocked && status === 'error' ? errorMessage ?? 'Unable to load plaintiffs.' : null;
  const showEmpty = !isDemoLocked && !isLoading && !displayError && !hasRows;

  const handleRowNavigate = useCallback(
    (row: PlaintiffWorkbenchRow) => {
      if (!row.plaintiffId) {
        return;
      }
      navigate(`/plaintiffs/${row.plaintiffId}`);
    },
    [navigate],
  );

  return (
    <section className="df-card space-y-6">
      <SectionHeader
        title="Plaintiff workbench"
        description="See exposure, outreach state, and enforcement momentum without leaving the console."
        actions={<RefreshButton onClick={handleRefresh} isLoading={isLoading} hasData={rows.length > 0} />}
      />

      {isDemoLocked ? (
        <DemoLockCard description={lockMessage ?? DEFAULT_DEMO_LOCK_MESSAGE} />
      ) : (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div className="flex flex-wrap gap-2">
              {STATUS_FILTERS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setStatusFilter(option.value)}
                  className={statusFilterButtonClass(statusFilter === option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <div className="w-full sm:w-72">
              <label htmlFor="plaintiff-search" className="sr-only">
                Search plaintiffs
              </label>
              <div className="relative">
                <input
                  id="plaintiff-search"
                  type="search"
                  value={searchTerm}
                  onChange={handleSearch}
                  placeholder="Search name or firm"
                  className="w-full rounded-full border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
                  autoComplete="off"
                />
                {searchTerm ? (
                  <button
                    type="button"
                    onClick={() => setSearchTerm('')}
                    className="absolute inset-y-0 right-3 flex items-center text-slate-400 transition hover:text-slate-600"
                    aria-label="Clear search"
                  >
                    ×
                  </button>
                ) : null}
              </div>
            </div>
          </div>

          <div className="overflow-hidden rounded-2xl border border-slate-100">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-100 text-left">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <HeaderCell>Plaintiff</HeaderCell>
                    <HeaderCell>Firm</HeaderCell>
                    <HeaderCell>Cases</HeaderCell>
                    <HeaderCell>Total judgment</HeaderCell>
                    <HeaderCell>Status</HeaderCell>
                    <HeaderCell>Enforcement active</HeaderCell>
                    <HeaderCell>Enforcement planning</HeaderCell>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-sm text-slate-700">
                  {showSkeleton ? <SkeletonRows /> : null}
                  {displayError && !isLoading ? <ErrorRow message={displayError} onRetry={handleRefresh} /> : null}
                  {showEmpty ? <EmptyRow /> : null}
                  {hasRows
                    ? filteredRows.map((row) => (
                        <TableRow key={row.plaintiffId} row={row} onNavigate={handleRowNavigate} />
                      ))
                    : null}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function statusFilterButtonClass(isActive: boolean): string {
  return isActive
    ? 'inline-flex items-center rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow-sm'
    : 'inline-flex items-center rounded-full border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800';
}

function HeaderCell({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-3 sm:px-6">{children}</th>;
}

function DataCell({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <td className={`px-4 py-4 sm:px-6 ${className}`.trim()}>{children}</td>;
}

function TableRow({
  row,
  onNavigate,
}: {
  row: PlaintiffWorkbenchRow;
  onNavigate: (row: PlaintiffWorkbenchRow) => void;
}) {
  const handleClick = () => onNavigate(row);
  const handleKeyDown = (event: React.KeyboardEvent<HTMLTableRowElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onNavigate(row);
    }
  };

  return (
    <tr
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      className="cursor-pointer transition hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500/40"
    >
      <DataCell className="font-semibold text-slate-800">{row.plaintiffName}</DataCell>
      <DataCell>{row.firmName}</DataCell>
      <DataCell>{row.caseCount.toLocaleString()}</DataCell>
      <DataCell>{formatCurrency(row.totalJudgmentAmount)}</DataCell>
      <DataCell>
        <span className={statusBadgeClass(row.status)}>{formatStatusLabel(row.statusLabel)}</span>
      </DataCell>
      <DataCell>{formatCount(row.enforcementActiveCases)}</DataCell>
      <DataCell>{formatCount(row.enforcementPlanningCases)}</DataCell>
    </tr>
  );
}

function formatCount(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return '—';
  }
  return value.toLocaleString();
}

function formatStatusLabel(label: string): string {
  const trimmed = label.trim();
  if (!trimmed) {
    return 'Untracked';
  }
  return trimmed.replace(/\s+/g, ' ');
}

function statusBadgeClass(status: PlaintiffStatusCode): string {
  switch (status) {
    case 'new':
      return 'inline-flex w-max items-center rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700';
    case 'contacted':
      return 'inline-flex w-max items-center rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700';
    case 'qualified':
      return 'inline-flex w-max items-center rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700';
    case 'sent_agreement':
      return 'inline-flex w-max items-center rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700';
    case 'signed':
      return 'inline-flex w-max items-center rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-800';
    case 'lost':
      return 'inline-flex w-max items-center rounded-full bg-rose-50 px-2.5 py-1 text-xs font-semibold text-rose-700';
    case 'unknown':
    default:
      return 'inline-flex w-max items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700';
  }
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: TABLE_SKELETON_ROWS }).map((_, rowIndex) => (
        <tr key={`skeleton-${rowIndex}`} className="animate-pulse">
          {Array.from({ length: TABLE_COLUMN_COUNT }).map((__, colIndex) => (
            <td key={`skeleton-${rowIndex}-${colIndex}`} className="px-4 py-4 sm:px-6">
              <div className="h-4 rounded bg-slate-200" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

function EmptyRow() {
  return (
    <tr>
      <td colSpan={TABLE_COLUMN_COUNT} className="px-4 py-12 text-center text-sm text-slate-500 sm:px-6">
        No plaintiffs match these filters yet. Adjust the status filter or clear your search to see more exposure.
      </td>
    </tr>
  );
}

function ErrorRow({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <tr>
      <td colSpan={TABLE_COLUMN_COUNT} className="px-4 py-6 text-sm text-rose-600 sm:px-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <p>We couldn’t load plaintiffs: {message}</p>
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center rounded-full bg-rose-600 px-4 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:bg-rose-700"
          >
            Retry
          </button>
        </div>
      </td>
    </tr>
  );
}
