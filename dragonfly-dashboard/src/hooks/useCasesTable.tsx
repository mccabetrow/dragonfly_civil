/**
 * useCasesTable - Data management hook for CasesPage
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Wraps useCasesDashboard and provides:
 * - Filtered & sorted row data
 * - Tier filter state (persisted)
 * - Search term state (persisted)
 * - Pre-built DataTable columns
 * - Global refresh subscription
 * - Case selection for drawer
 *
 * Designed to work with CaseTable and CaseDetailDrawer components.
 */

import { useMemo, useCallback, useState } from 'react';
import {
  useCasesDashboard,
  type CasesDashboardRow,
} from './useCasesDashboard';
import { usePersistedState, PERSISTED_KEYS } from './ui/usePersistedState';
import { useOnRefresh } from '../context/RefreshContext';
import type { Column } from '../components/ui/DataTable';
import { TierBadge } from '../components/ui/Badge';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type CasesTierFilter = 'All' | 'A' | 'B' | 'C';

/** Return type for the hook */
export interface UseCasesTableReturn {
  /** All rows from the dashboard (unfiltered) */
  allRows: CasesDashboardRow[];
  /** Filtered rows ready for display */
  displayRows: CasesDashboardRow[];
  /** Current tier filter value */
  tierFilter: CasesTierFilter;
  /** Set tier filter */
  setTierFilter: (tier: CasesTierFilter) => void;
  /** Current search term */
  searchTerm: string;
  /** Set search term */
  setSearchTerm: (term: string) => void;
  /** Pre-built columns for DataTable */
  columns: Column<CasesDashboardRow>[];
  /** Currently selected case ID */
  selectedCaseId: string | null;
  /** Set selected case for drawer */
  setSelectedCaseId: (id: string | null) => void;
  /** Selected case row data */
  selectedCase: CasesDashboardRow | null;
  /** Loading state */
  isLoading: boolean;
  /** Error message */
  error: string | null;
  /** Data state */
  status: 'idle' | 'loading' | 'ready' | 'error' | 'demo_locked';
  /** Refetch data */
  refetch: () => void;
  /** Total count */
  totalCount: number;
  /** Reset all filters */
  resetFilters: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

export const CASES_TIER_OPTIONS: CasesTierFilter[] = ['All', 'A', 'B', 'C'];

// ═══════════════════════════════════════════════════════════════════════════
// FORMATTERS
// ═══════════════════════════════════════════════════════════════════════════

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

export function formatCurrency(value: number | null): string {
  if (typeof value !== 'number') return '—';
  return currencyFormatter.format(value);
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK IMPLEMENTATION
// ═══════════════════════════════════════════════════════════════════════════

export function useCasesTable(): UseCasesTableReturn {
  // Data layer
  const { data, status, error, errorMessage, refetch } = useCasesDashboard();

  // Subscribe to global refresh
  useOnRefresh(refetch);

  // Persisted filter state
  const [tierFilter, setTierFilter, resetTier] = usePersistedState<CasesTierFilter>(
    PERSISTED_KEYS.CASES_TIER,
    'All'
  );

  const [searchTerm, setSearchTerm, resetSearch] = usePersistedState<string>(
    PERSISTED_KEYS.CASES_SEARCH,
    ''
  );

  // Case selection for drawer
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);

  // All rows from data (or empty array)
  const allRows = useMemo(() => data?.rows ?? [], [data]);
  const totalCount = data?.totalCount ?? 0;

  // Filtered rows
  const displayRows = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return allRows.filter((row) => {
      // Tier filter
      if (tierFilter !== 'All') {
        const normalized = row.collectabilityTier?.toUpperCase() ?? '';
        if (normalized !== tierFilter) return false;
      }
      // Search filter (case number)
      if (term && !row.caseNumber.toLowerCase().includes(term)) {
        return false;
      }
      return true;
    });
  }, [allRows, tierFilter, searchTerm]);

  // Selected case row
  const selectedCase = useMemo(() => {
    if (!selectedCaseId) return null;
    return allRows.find((row) => row.judgmentId === selectedCaseId) ?? null;
  }, [selectedCaseId, allRows]);

  // Reset all filters
  const resetFilters = useCallback(() => {
    resetTier();
    resetSearch();
  }, [resetTier, resetSearch]);

  // Pre-built columns for DataTable
  const columns = useMemo<Column<CasesDashboardRow>[]>(
    () => [
      {
        key: 'caseNumber',
        header: 'Case Number',
        sortable: true,
        cell: (row) => (
          <span className="font-medium text-slate-900">{row.caseNumber}</span>
        ),
      },
      {
        key: 'plaintiffName',
        header: 'Plaintiff',
        cell: (row) => (
          <span className="text-slate-700">{row.plaintiffName}</span>
        ),
      },
      {
        key: 'defendantName',
        header: 'Defendant',
        cell: (row) => (
          <span className="text-slate-600">{row.defendantName}</span>
        ),
      },
      {
        key: 'judgmentAmount',
        header: 'Amount',
        sortable: true,
        align: 'right' as const,
        cell: (row) => (
          <span className="tabular-nums font-medium">{formatCurrency(row.judgmentAmount)}</span>
        ),
      },
      {
        key: 'collectabilityTier',
        header: 'Tier',
        sortable: true,
        width: '100px',
        cell: (row) => {
          const tier = row.collectabilityTier?.toUpperCase() ?? null;
          if (!tier || !['A', 'B', 'C'].includes(tier)) {
            return <span className="text-slate-400">—</span>;
          }
          return <TierBadge tier={tier} size="sm" />;
        },
      },
      {
        key: 'enforcementStageLabel',
        header: 'Status',
        cell: (row) => (
          <span className="text-sm text-slate-600">{row.enforcementStageLabel}</span>
        ),
      },
    ],
    []
  );

  // Derived states
  const isLoading = status === 'idle' || status === 'loading';
  const errorText = errorMessage ?? (error instanceof Error ? error.message : error) ?? null;

  return {
    allRows,
    displayRows,
    tierFilter,
    setTierFilter,
    searchTerm,
    setSearchTerm,
    columns,
    selectedCaseId,
    setSelectedCaseId,
    selectedCase,
    isLoading,
    error: errorText,
    status,
    refetch,
    totalCount,
    resetFilters,
  };
}

export default useCasesTable;
