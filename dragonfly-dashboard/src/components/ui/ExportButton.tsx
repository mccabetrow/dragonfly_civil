/**
 * ExportButton - Download current view data as CSV or JSON
 *
 * Provides auditability and data portability for executive reporting.
 */

import { type FC, useState, useCallback } from 'react';
import { Download, FileJson, FileSpreadsheet, ChevronDown } from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import type { ExportFormat } from '../../utils/dataExport';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface ExportButtonProps<T extends Record<string, unknown>> {
  /** Data to export */
  data: T[];
  /** Function to perform the export */
  onExport: (format: ExportFormat) => void;
  /** Button label */
  label?: string;
  /** Whether data is still loading */
  loading?: boolean;
  /** Disable the button */
  disabled?: boolean;
  /** Button size */
  size?: 'sm' | 'md';
  /** Additional CSS classes */
  className?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export function ExportButton<T extends Record<string, unknown>>({
  data,
  onExport,
  label = 'Export',
  loading = false,
  disabled = false,
  size = 'md',
  className,
}: ExportButtonProps<T>): ReturnType<FC> {
  const [isOpen, setIsOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  const handleExport = useCallback(
    async (format: ExportFormat) => {
      setExporting(true);
      try {
        await onExport(format);
      } finally {
        setExporting(false);
        setIsOpen(false);
      }
    },
    [onExport]
  );

  const isDisabled = disabled || loading || data.length === 0;
  const showSpinner = loading || exporting;

  const sizeClasses = {
    sm: 'px-2.5 py-1.5 text-xs gap-1.5',
    md: 'px-3 py-2 text-sm gap-2',
  };

  return (
    <div className={cn('relative inline-block', className)}>
      {/* Main button */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        disabled={isDisabled}
        className={cn(
          'inline-flex items-center justify-center rounded-full border font-semibold uppercase tracking-wide transition',
          'border-slate-200 bg-white text-slate-700 shadow-sm',
          'hover:border-slate-300 hover:bg-slate-50',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2',
          isDisabled && 'cursor-not-allowed opacity-50',
          sizeClasses[size]
        )}
        aria-haspopup="true"
        aria-expanded={isOpen}
      >
        {showSpinner ? (
          <span className="inline-flex h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-transparent" />
        ) : (
          <Download className="h-4 w-4" aria-hidden="true" />
        )}
        {label}
        <ChevronDown
          className={cn('h-3 w-3 transition-transform', isOpen && 'rotate-180')}
          aria-hidden="true"
        />
      </button>

      {/* Dropdown menu */}
      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => setIsOpen(false)}
            aria-hidden="true"
          />

          {/* Menu */}
          <div className="absolute right-0 z-20 mt-2 w-44 origin-top-right rounded-xl border border-slate-200 bg-white py-1 shadow-lg ring-1 ring-black/5">
            <button
              type="button"
              onClick={() => handleExport('csv')}
              className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
            >
              <FileSpreadsheet className="h-4 w-4 text-emerald-600" aria-hidden="true" />
              Download CSV
            </button>
            <button
              type="button"
              onClick={() => handleExport('json')}
              className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
            >
              <FileJson className="h-4 w-4 text-amber-600" aria-hidden="true" />
              Download JSON
            </button>
            <div className="mx-4 my-1 border-t border-slate-100" />
            <p className="px-4 py-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">
              {data.length} record{data.length !== 1 ? 's' : ''}
            </p>
          </div>
        </>
      )}
    </div>
  );
}

export default ExportButton;
