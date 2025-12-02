import { type FC, type ReactNode, useState, useMemo, useCallback } from 'react';
import { ChevronUp, ChevronDown, ChevronsUpDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import { Button } from './Button';
import { TableSkeleton } from './Skeleton';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface Column<T> {
  key: string;
  header: string | ReactNode;
  cell: (row: T, index: number) => ReactNode;
  sortable?: boolean;
  sortKey?: keyof T;
  width?: string;
  align?: 'left' | 'center' | 'right';
  className?: string;
}

export interface DataTableProps<T> {
  data: T[];
  columns: Column<T>[];
  keyExtractor: (row: T, index: number) => string;
  
  // State
  loading?: boolean;
  error?: string | null;
  
  // Pagination
  pageSize?: number;
  showPagination?: boolean;
  
  // Sorting
  defaultSortKey?: string;
  defaultSortDirection?: 'asc' | 'desc';
  onSort?: (key: string, direction: 'asc' | 'desc') => void;
  
  // Selection
  selectable?: boolean;
  selectedKeys?: Set<string>;
  onSelectionChange?: (keys: Set<string>) => void;
  
  // Row interactions
  onRowClick?: (row: T, index: number) => void;
  rowClassName?: (row: T, index: number) => string;
  
  // Empty state
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: ReactNode;
  
  // Styling
  className?: string;
  compact?: boolean;
  stickyHeader?: boolean;
}

type SortDirection = 'asc' | 'desc' | null;

// ═══════════════════════════════════════════════════════════════════════════
// DATA TABLE COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export function DataTable<T>({
  data,
  columns,
  keyExtractor,
  loading = false,
  error = null,
  pageSize = 25,
  showPagination = true,
  defaultSortKey,
  defaultSortDirection = 'desc',
  onSort,
  selectable = false,
  selectedKeys = new Set(),
  onSelectionChange,
  onRowClick,
  rowClassName,
  emptyTitle = 'No data',
  emptyDescription = 'There are no items to display.',
  emptyAction,
  className,
  compact = false,
  stickyHeader = false,
}: DataTableProps<T>) {
  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);
  
  // Sort state
  const [sortKey, setSortKey] = useState<string | null>(defaultSortKey ?? null);
  const [sortDirection, setSortDirection] = useState<SortDirection>(
    defaultSortKey ? defaultSortDirection : null
  );

  // Sort handler
  const handleSort = useCallback(
    (key: string) => {
      let newDirection: SortDirection;
      
      if (sortKey !== key) {
        newDirection = 'desc';
      } else if (sortDirection === 'desc') {
        newDirection = 'asc';
      } else if (sortDirection === 'asc') {
        newDirection = null;
      } else {
        newDirection = 'desc';
      }

      setSortKey(newDirection ? key : null);
      setSortDirection(newDirection);
      setCurrentPage(1);

      if (onSort && newDirection) {
        onSort(key, newDirection);
      }
    },
    [sortKey, sortDirection, onSort]
  );

  // Sorted data
  const sortedData = useMemo(() => {
    if (!sortKey || !sortDirection) return data;

    const column = columns.find((c) => c.key === sortKey || c.sortKey === sortKey);
    if (!column) return data;

    const accessor = column.sortKey ?? (column.key as keyof T);

    return [...data].sort((a, b) => {
      const aVal = a[accessor];
      const bVal = b[accessor];

      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;

      let comparison = 0;
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        comparison = aVal - bVal;
      } else if (typeof aVal === 'string' && typeof bVal === 'string') {
        comparison = aVal.localeCompare(bVal);
      } else {
        comparison = String(aVal).localeCompare(String(bVal));
      }

      return sortDirection === 'desc' ? -comparison : comparison;
    });
  }, [data, sortKey, sortDirection, columns]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(sortedData.length / pageSize));
  const paginatedData = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return sortedData.slice(start, start + pageSize);
  }, [sortedData, currentPage, pageSize]);

  // Selection handlers
  const handleSelectAll = useCallback(() => {
    if (!onSelectionChange) return;

    const allKeys = new Set(paginatedData.map((row, i) => keyExtractor(row, i)));
    const allSelected = [...allKeys].every((key) => selectedKeys.has(key));

    if (allSelected) {
      const newSelection = new Set(selectedKeys);
      allKeys.forEach((key) => newSelection.delete(key));
      onSelectionChange(newSelection);
    } else {
      onSelectionChange(new Set([...selectedKeys, ...allKeys]));
    }
  }, [paginatedData, keyExtractor, selectedKeys, onSelectionChange]);

  const handleSelectRow = useCallback(
    (key: string) => {
      if (!onSelectionChange) return;

      const newSelection = new Set(selectedKeys);
      if (newSelection.has(key)) {
        newSelection.delete(key);
      } else {
        newSelection.add(key);
      }
      onSelectionChange(newSelection);
    },
    [selectedKeys, onSelectionChange]
  );

  // Cell padding based on compact mode
  const cellPadding = compact ? 'px-3 py-2' : 'px-4 py-3';
  const headerPadding = compact ? 'px-3 py-2.5' : 'px-4 py-3';

  // Loading state
  if (loading) {
    return <TableSkeleton rows={pageSize} columns={columns.length} />;
  }

  // Error state
  if (error) {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-center">
        <p className="text-sm font-medium text-rose-700">{error}</p>
      </div>
    );
  }

  // Empty state
  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/50 px-6 py-12 text-center">
        <p className="text-base font-semibold text-slate-900">{emptyTitle}</p>
        <p className="mt-1 text-sm text-slate-600">{emptyDescription}</p>
        {emptyAction && <div className="mt-4">{emptyAction}</div>}
      </div>
    );
  }

  return (
    <div className={cn('overflow-hidden rounded-xl border border-slate-200/80', className)}>
      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead className={cn(
            'bg-slate-50/80 border-b border-slate-200/60',
            stickyHeader && 'sticky top-0 z-10 backdrop-blur-sm bg-slate-50/95'
          )}>
            <tr>
              {selectable && (
                <th className={cn(headerPadding, 'w-10')}>
                  <input
                    type="checkbox"
                    checked={
                      paginatedData.length > 0 &&
                      paginatedData.every((row, i) =>
                        selectedKeys.has(keyExtractor(row, i))
                      )
                    }
                    onChange={handleSelectAll}
                    className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                </th>
              )}
              {columns.map((column) => (
                <th
                  key={column.key}
                  className={cn(
                    headerPadding,
                    'text-left text-[11px] font-bold uppercase tracking-wider text-slate-500',
                    column.sortable && 'cursor-pointer select-none transition-colors hover:bg-slate-100/80 hover:text-slate-700',
                    column.align === 'center' && 'text-center',
                    column.align === 'right' && 'text-right',
                    column.className
                  )}
                  style={{ width: column.width }}
                  onClick={column.sortable ? () => handleSort(column.key) : undefined}
                >
                  <span className="inline-flex items-center gap-1">
                    {column.header}
                    {column.sortable && (
                      <SortIndicator
                        active={sortKey === column.key}
                        direction={sortKey === column.key ? sortDirection : null}
                      />
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {paginatedData.map((row, index) => {
              const key = keyExtractor(row, index);
              const isSelected = selectedKeys.has(key);
              const isClickable = Boolean(onRowClick);
              const isEven = index % 2 === 1;

              return (
                <tr
                  key={key}
                  className={cn(
                    'transition-colors duration-100',
                    isEven ? 'bg-slate-50/40' : 'bg-white',
                    isClickable && 'cursor-pointer hover:bg-indigo-50/50',
                    isSelected && 'bg-indigo-50/70 relative before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-indigo-500',
                    rowClassName?.(row, index)
                  )}
                  onClick={isClickable ? () => onRowClick?.(row, index) : undefined}
                  tabIndex={isClickable ? 0 : undefined}
                  onKeyDown={
                    isClickable
                      ? (e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            onRowClick?.(row, index);
                          }
                        }
                      : undefined
                  }
                >
                  {selectable && (
                    <td className={cellPadding} onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => handleSelectRow(key)}
                        className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                      />
                    </td>
                  )}
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={cn(
                        cellPadding,
                        'text-sm text-slate-700',
                        column.align === 'center' && 'text-center',
                        column.align === 'right' && 'text-right',
                        column.className
                      )}
                    >
                      {column.cell(row, index)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {showPagination && totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3">
          <span className="text-sm text-slate-600">
            Showing {(currentPage - 1) * pageSize + 1}–
            {Math.min(currentPage * pageSize, sortedData.length)} of{' '}
            {sortedData.length.toLocaleString()}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              leftIcon={<ChevronLeft className="h-4 w-4" />}
            >
              Prev
            </Button>
            <span className="text-sm text-slate-600">
              Page {currentPage} of {totalPages}
            </span>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
              rightIcon={<ChevronRight className="h-4 w-4" />}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// SORT INDICATOR
// ═══════════════════════════════════════════════════════════════════════════

interface SortIndicatorProps {
  active: boolean;
  direction: SortDirection;
}

const SortIndicator: FC<SortIndicatorProps> = ({ active, direction }) => {
  if (!active || !direction) {
    return <ChevronsUpDown className="h-3.5 w-3.5 text-slate-400" />;
  }

  return direction === 'asc' ? (
    <ChevronUp className="h-3.5 w-3.5 text-slate-700" />
  ) : (
    <ChevronDown className="h-3.5 w-3.5 text-slate-700" />
  );
};

export default DataTable;
