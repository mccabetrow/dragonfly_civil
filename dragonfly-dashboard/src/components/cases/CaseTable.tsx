/**
 * CaseTable - Industrial-grade case list with keyboard navigation
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Wraps DataTable with case-specific enhancements:
 * - Keyboard navigation (arrow keys, Enter to select)
 * - Row click to open drawer
 * - Visual selection highlight
 * - Responsive columns
 */

import { type FC, useCallback, useRef, useEffect } from 'react';
import DataTable from '../ui/DataTable';
import type { CasesDashboardRow } from '../../hooks/useCasesDashboard';
import type { Column } from '../ui/DataTable';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface CaseTableProps {
  /** Case rows to display */
  rows: CasesDashboardRow[];
  /** Column definitions */
  columns: Column<CasesDashboardRow>[];
  /** Loading state */
  loading: boolean;
  /** Error message */
  error?: string;
  /** Currently selected case ID */
  selectedCaseId: string | null;
  /** Handler when a case is selected */
  onSelectCase: (caseId: string) => void;
  /** Page size for pagination */
  pageSize?: number;
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const CaseTable: FC<CaseTableProps> = ({
  rows,
  columns,
  loading,
  error,
  selectedCaseId,
  onSelectCase,
  pageSize = 25,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const focusedIndexRef = useRef<number>(0);

  // Keyboard navigation
  useEffect(() => {
    const container = containerRef.current;
    if (!container || rows.length === 0) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Only handle if focus is inside the table
      if (!container.contains(document.activeElement)) return;

      switch (e.key) {
        case 'ArrowDown': {
          e.preventDefault();
          focusedIndexRef.current = Math.min(focusedIndexRef.current + 1, rows.length - 1);
          focusRowAtIndex(container, focusedIndexRef.current);
          break;
        }
        case 'ArrowUp': {
          e.preventDefault();
          focusedIndexRef.current = Math.max(focusedIndexRef.current - 1, 0);
          focusRowAtIndex(container, focusedIndexRef.current);
          break;
        }
        case 'Enter':
        case ' ': {
          e.preventDefault();
          const row = rows[focusedIndexRef.current];
          if (row) {
            onSelectCase(row.judgmentId);
          }
          break;
        }
        case 'Home': {
          e.preventDefault();
          focusedIndexRef.current = 0;
          focusRowAtIndex(container, 0);
          break;
        }
        case 'End': {
          e.preventDefault();
          focusedIndexRef.current = rows.length - 1;
          focusRowAtIndex(container, rows.length - 1);
          break;
        }
      }
    };

    container.addEventListener('keydown', handleKeyDown);
    return () => container.removeEventListener('keydown', handleKeyDown);
  }, [rows, onSelectCase]);

  // Row click handler
  const handleRowClick = useCallback(
    (row: CasesDashboardRow, index: number) => {
      focusedIndexRef.current = index;
      onSelectCase(row.judgmentId);
    },
    [onSelectCase]
  );

  // Custom row styling for selected state
  const rowClassName = useCallback(
    (row: CasesDashboardRow) => {
      if (row.judgmentId === selectedCaseId) {
        return 'bg-blue-50/70 border-l-2 border-l-blue-500';
      }
      return '';
    },
    [selectedCaseId]
  );

  return (
    <div ref={containerRef} className="focus-within:outline-none" role="grid" aria-label="Cases table">
      <DataTable
        data={rows}
        columns={columns}
        keyExtractor={(row) => row.judgmentId}
        loading={loading}
        error={error}
        pageSize={pageSize}
        showPagination
        stickyHeader
        onRowClick={handleRowClick}
        rowClassName={rowClassName}
        emptyTitle="No cases found"
        emptyDescription="Try adjusting your filters to see more results."
        compact
      />
    </div>
  );
};

/**
 * Focus the row at the given index in the table
 */
function focusRowAtIndex(container: HTMLElement, index: number): void {
  const rows = container.querySelectorAll('tbody tr[tabindex]');
  const targetRow = rows[index] as HTMLElement | undefined;
  if (targetRow) {
    targetRow.focus();
    // Scroll into view if needed
    targetRow.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}

export default CaseTable;
