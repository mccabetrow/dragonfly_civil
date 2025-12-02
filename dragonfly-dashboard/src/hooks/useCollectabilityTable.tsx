/**
 * useCollectabilityTable - Data management hook for CollectabilityPage
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Wraps useCollectabilitySnapshot and provides:
 * - Filtered & sorted row data
 * - Tier filter state (persisted)
 * - Search term state (persisted)
 * - Sort state (persisted)
 * - Pre-built DataTable columns
 * - Global refresh subscription
 *
 * Designed to work with the DataTable component for a clean separation
 * between data management and presentation.
 */

import { useMemo, useCallback } from 'react';
import {
  useCollectabilitySnapshot,
  type CollectabilitySnapshotRow,
} from './useCollectabilitySnapshot';
import { usePersistedState, PERSISTED_KEYS } from './ui/usePersistedState';
import { useOnRefresh } from '../context/RefreshContext';
import type { Column } from '../components/ui/DataTable';
import { TierBadge } from '../components/ui/Badge';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type CollectabilityTier = 'A' | 'B' | 'C';
export type TierFilter = CollectabilityTier | 'All';
export type SortDirection = 'asc' | 'desc';

/** Available columns for sorting */
export type CollectabilitySortKey = 'judgment_amount' | 'age_days' | 'collectability_tier' | 'case_number';

/** Tier count summary */
export interface TierCounts {
  A: number;
  B: number;
  C: number;
  total: number;
}

/** Return type for the hook */
export interface UseCollectabilityTableReturn {
  /** All rows from the snapshot (unfiltered) */
  allRows: CollectabilitySnapshotRow[];
  /** Filtered and sorted rows ready for display */
  displayRows: CollectabilitySnapshotRow[];
  /** Current tier filter value */
  tierFilter: TierFilter;
  /** Set tier filter */
  setTierFilter: (tier: TierFilter) => void;
  /** Current search term */
  searchTerm: string;
  /** Set search term */
  setSearchTerm: (term: string) => void;
  /** Current sort column */
  sortKey: CollectabilitySortKey;
  /** Set sort column */
  setSortKey: (key: CollectabilitySortKey) => void;
  /** Current sort direction */
  sortDirection: SortDirection;
  /** Set sort direction */
  setSortDirection: (dir: SortDirection) => void;
  /** Toggle sort for a column (handles asc/desc flip) */
  handleSort: (key: CollectabilitySortKey) => void;
  /** Tier counts from unfiltered data */
  tierCounts: TierCounts;
  /** Pre-built columns for DataTable */
  columns: Column<CollectabilitySnapshotRow>[];
  /** Loading state */
  isLoading: boolean;
  /** Error state */
  error: string | null;
  /** Data state: 'idle' | 'loading' | 'ready' | 'error' */
  status: 'idle' | 'loading' | 'ready' | 'error' | 'demo_locked';
  /** Refetch data */
  refetch: () => void;
  /** Reset all filters to defaults */
  resetFilters: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

export const TIER_OPTIONS: TierFilter[] = ['All', 'A', 'B', 'C'];

const DEFAULT_SORT_KEY: CollectabilitySortKey = 'judgment_amount';
const DEFAULT_SORT_DIRECTION: SortDirection = 'desc';
const DEFAULT_TIER_FILTER: TierFilter = 'All';
const DEFAULT_SEARCH_TERM = '';

// ═══════════════════════════════════════════════════════════════════════════
// FORMATTERS (reusable across components)
// ═══════════════════════════════════════════════════════════════════════════

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

const dateTimeFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeStyle: 'short',
});

export function formatCurrency(value: number | null): string {
  if (typeof value !== 'number') return '—';
  return currencyFormatter.format(value);
}

export function formatTimestamp(value: string | null): string {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  return dateTimeFormatter.format(parsed);
}

export function formatAgeDays(value: number | null): string {
  if (typeof value !== 'number') return '—';
  return `${value.toLocaleString()} days`;
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK IMPLEMENTATION
// ═══════════════════════════════════════════════════════════════════════════

export function useCollectabilityTable(): UseCollectabilityTableReturn {
  // Data layer
  const { data, status, error, errorMessage, refetch } = useCollectabilitySnapshot();

  // Subscribe to global refresh
  useOnRefresh(refetch);

  // Persisted filter state
  const [tierFilter, setTierFilter, resetTier] = usePersistedState<TierFilter>(
    PERSISTED_KEYS.COLLECTABILITY_TIER,
    DEFAULT_TIER_FILTER
  );

  const [searchTerm, setSearchTerm, resetSearch] = usePersistedState<string>(
    PERSISTED_KEYS.COLLECTABILITY_SEARCH,
    DEFAULT_SEARCH_TERM
  );

  const [sortKey, setSortKey, resetSortKey] = usePersistedState<CollectabilitySortKey>(
    PERSISTED_KEYS.COLLECTABILITY_SORT_KEY,
    DEFAULT_SORT_KEY
  );

  const [sortDirection, setSortDirection, resetSortDir] = usePersistedState<SortDirection>(
    PERSISTED_KEYS.COLLECTABILITY_SORT_DIR,
    DEFAULT_SORT_DIRECTION
  );

  // All rows from data (or empty array)
  const allRows = useMemo(() => data ?? [], [data]);

  // Tier counts from unfiltered data
  const tierCounts = useMemo<TierCounts>(() => {
    const counts: TierCounts = { A: 0, B: 0, C: 0, total: 0 };
    for (const row of allRows) {
      counts.total++;
      const tier = row.collectability_tier?.toUpperCase();
      if (tier === 'A') counts.A++;
      else if (tier === 'B') counts.B++;
      else if (tier === 'C') counts.C++;
    }
    return counts;
  }, [allRows]);

  // Filtered rows
  const filteredRows = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return allRows.filter((row) => {
      // Tier filter
      if (tierFilter !== 'All' && row.collectability_tier?.toUpperCase() !== tierFilter) {
        return false;
      }
      // Search filter (case number)
      if (term && !(row.case_number ?? '').toLowerCase().includes(term)) {
        return false;
      }
      return true;
    });
  }, [allRows, tierFilter, searchTerm]);

  // Sorted rows
  const displayRows = useMemo(() => {
    return [...filteredRows].sort((a, b) => {
      let comparison = 0;

      switch (sortKey) {
        case 'judgment_amount': {
          const aVal = typeof a.judgment_amount === 'number' ? a.judgment_amount : -Infinity;
          const bVal = typeof b.judgment_amount === 'number' ? b.judgment_amount : -Infinity;
          comparison = aVal - bVal;
          break;
        }
        case 'age_days': {
          const aVal = typeof a.age_days === 'number' ? a.age_days : -Infinity;
          const bVal = typeof b.age_days === 'number' ? b.age_days : -Infinity;
          comparison = aVal - bVal;
          break;
        }
        case 'collectability_tier': {
          const tierOrder: Record<string, number> = { A: 0, B: 1, C: 2 };
          const aVal = tierOrder[a.collectability_tier?.toUpperCase() ?? 'C'] ?? 3;
          const bVal = tierOrder[b.collectability_tier?.toUpperCase() ?? 'C'] ?? 3;
          comparison = aVal - bVal;
          break;
        }
        case 'case_number':
        default: {
          comparison = (a.case_number ?? '').localeCompare(b.case_number ?? '');
          break;
        }
      }

      return sortDirection === 'asc' ? comparison : -comparison;
    });
  }, [filteredRows, sortKey, sortDirection]);

  // Sort handler (toggles direction if same column, otherwise sets new column)
  const handleSort = useCallback(
    (key: CollectabilitySortKey) => {
      if (key === sortKey) {
        setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      } else {
        setSortKey(key);
        setSortDirection('desc');
      }
    },
    [sortKey, setSortDirection, setSortKey]
  );

  // Reset all filters
  const resetFilters = useCallback(() => {
    resetTier();
    resetSearch();
    resetSortKey();
    resetSortDir();
  }, [resetTier, resetSearch, resetSortKey, resetSortDir]);

  // Pre-built columns for DataTable
  const columns = useMemo<Column<CollectabilitySnapshotRow>[]>(
    () => [
      {
        key: 'case_number',
        header: 'Case Number',
        sortable: true,
        sortKey: 'case_number',
        cell: (row) => (
          <span className="font-medium text-slate-900">{row.case_number ?? '—'}</span>
        ),
      },
      {
        key: 'collectability_tier',
        header: 'Tier',
        sortable: true,
        sortKey: 'collectability_tier',
        width: '100px',
        cell: (row) => {
          const tier = row.collectability_tier?.toUpperCase() ?? 'C';
          return <TierBadge tier={tier} size="sm" />;
        },
      },
      {
        key: 'judgment_amount',
        header: 'Judgment Amount',
        sortable: true,
        sortKey: 'judgment_amount',
        align: 'right' as const,
        cell: (row) => (
          <span className="tabular-nums">{formatCurrency(row.judgment_amount)}</span>
        ),
      },
      {
        key: 'age_days',
        header: 'Age',
        sortable: true,
        sortKey: 'age_days',
        align: 'right' as const,
        cell: (row) => (
          <span className="tabular-nums">{formatAgeDays(row.age_days)}</span>
        ),
      },
      {
        key: 'last_enrichment_status',
        header: 'Enrichment Status',
        cell: (row) => (
          <span className="text-slate-600">{row.last_enrichment_status ?? '—'}</span>
        ),
      },
      {
        key: 'last_enriched_at',
        header: 'Last Enriched',
        cell: (row) => (
          <span className="text-slate-500 text-sm">{formatTimestamp(row.last_enriched_at)}</span>
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
    sortKey,
    setSortKey,
    sortDirection,
    setSortDirection,
    handleSort,
    tierCounts,
    columns,
    isLoading,
    error: errorText,
    status,
    refetch,
    resetFilters,
  };
}

export default useCollectabilityTable;
