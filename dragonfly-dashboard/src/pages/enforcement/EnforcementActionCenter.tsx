/**
 * EnforcementActionCenter - Financial Terminal Style Action Center
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Dense data grid for enforcement operations:
 *   - Color-coded score badges (90+ Green, <50 Red)
 *   - Filter toolbar (Employed, Bank Assets, Min Score)
 *   - "Generate Packet" button per row with toast notifications
 *   - Real-time data from enforcement radar
 *
 * Design:
 *   - Dark theme: bg-slate-950, border-slate-800
 *   - Monospace numbers, dense table layout
 *   - framer-motion animations
 *
 * Route: /radar (replaces EnforcementRadarPage)
 */
import { type FC, useCallback, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Target,
  Filter,
  RefreshCw,
  ChevronUp,
  ChevronDown,
  Loader2,
  FileText,
  Briefcase,
  Building2,
  Gauge,
  X,
  Check,
  AlertCircle,
} from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import {
  useEnforcementRadar,
  computeRadarKPIs,
  type OfferStrategy,
  type RadarRow,
} from '../../hooks/useEnforcementRadar';
import { useEnforcementActions } from '../../hooks/useEnforcementActions';
import { useOnRefresh } from '../../context/RefreshContext';
import { telemetry } from '../../utils/logUiAction';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

type SortField = 'collectabilityScore' | 'judgmentAmount' | 'plaintiffName';
type SortDirection = 'asc' | 'desc';

interface SortConfig {
  field: SortField;
  direction: SortDirection;
}

interface FilterState {
  showOnlyEmployed: boolean;
  showOnlyBankAssets: boolean;
  minScore: number;
}

interface ToastState {
  id: string;
  type: 'loading' | 'success' | 'error';
  message: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function formatCurrency(value: number): string {
  if (value >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(2)}M`;
  }
  if (value >= 1_000) {
    return `$${Math.round(value / 1_000)}K`;
  }
  return `$${value.toFixed(0)}`;
}

function formatCurrencyFull(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

// ═══════════════════════════════════════════════════════════════════════════
// SCORE BADGE - Color-coded based on requirements
// ═══════════════════════════════════════════════════════════════════════════

interface ScoreBadgeProps {
  score: number | null;
}

const ScoreBadge: FC<ScoreBadgeProps> = ({ score }) => {
  if (score === null) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded font-mono text-xs bg-slate-800 text-slate-500">
        —
      </span>
    );
  }

  // Color coding per requirements: 90+ Green, <50 Red
  let colorClasses: string;
  if (score >= 90) {
    colorClasses = 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
  } else if (score >= 70) {
    colorClasses = 'bg-green-500/20 text-green-400 border-green-500/30';
  } else if (score >= 50) {
    colorClasses = 'bg-amber-500/20 text-amber-400 border-amber-500/30';
  } else {
    colorClasses = 'bg-red-500/20 text-red-400 border-red-500/30';
  }

  return (
    <span
      className={cn(
        'inline-flex items-center justify-center min-w-[2.5rem] px-2 py-0.5 rounded border font-mono text-xs font-bold tabular-nums',
        colorClasses
      )}
    >
      {score}
    </span>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// STRATEGY PILL
// ═══════════════════════════════════════════════════════════════════════════

interface StrategyPillProps {
  strategy: OfferStrategy;
}

const StrategyPill: FC<StrategyPillProps> = ({ strategy }) => {
  const config: Record<OfferStrategy, { label: string; classes: string }> = {
    BUY_CANDIDATE: {
      label: 'BUY',
      classes: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    },
    CONTINGENCY: {
      label: 'CONT',
      classes: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    },
    ENRICHMENT_PENDING: {
      label: 'PEND',
      classes: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    },
    LOW_PRIORITY: {
      label: 'LOW',
      classes: 'bg-slate-700/50 text-slate-500 border-slate-600/30',
    },
  };

  const { label, classes } = config[strategy];

  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded border font-mono text-xs font-bold uppercase tracking-wider',
        classes
      )}
    >
      {label}
    </span>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// FILTER TOOLBAR
// ═══════════════════════════════════════════════════════════════════════════

interface FilterToolbarProps {
  filters: FilterState;
  onFilterChange: (filters: FilterState) => void;
  totalCount: number;
  filteredCount: number;
}

const FilterToolbar: FC<FilterToolbarProps> = ({
  filters,
  onFilterChange,
  totalCount,
  filteredCount,
}) => {
  const toggleFilter = (key: keyof Omit<FilterState, 'minScore'>) => {
    onFilterChange({ ...filters, [key]: !filters[key] });
  };

  const setMinScore = (value: number) => {
    onFilterChange({ ...filters, minScore: value });
  };

  const clearFilters = () => {
    onFilterChange({
      showOnlyEmployed: false,
      showOnlyBankAssets: false,
      minScore: 0,
    });
  };

  const hasActiveFilters =
    filters.showOnlyEmployed || filters.showOnlyBankAssets || filters.minScore > 0;

  return (
    <div className="flex items-center gap-3 p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
      <Filter className="h-4 w-4 text-slate-500" />
      <span className="text-xs font-medium text-slate-400 uppercase tracking-wide">Filters:</span>

      {/* Show Only Employed */}
      <button
        onClick={() => toggleFilter('showOnlyEmployed')}
        className={cn(
          'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
          filters.showOnlyEmployed
            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
            : 'bg-slate-800 text-slate-400 border border-slate-700 hover:bg-slate-700'
        )}
      >
        <Briefcase className="h-3.5 w-3.5" />
        Employed
      </button>

      {/* Show Only Bank Assets */}
      <button
        onClick={() => toggleFilter('showOnlyBankAssets')}
        className={cn(
          'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
          filters.showOnlyBankAssets
            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
            : 'bg-slate-800 text-slate-400 border border-slate-700 hover:bg-slate-700'
        )}
      >
        <Building2 className="h-3.5 w-3.5" />
        Bank Assets
      </button>

      {/* Min Score > 80 */}
      <button
        onClick={() => setMinScore(filters.minScore > 0 ? 0 : 80)}
        className={cn(
          'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
          filters.minScore > 0
            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
            : 'bg-slate-800 text-slate-400 border border-slate-700 hover:bg-slate-700'
        )}
      >
        <Gauge className="h-3.5 w-3.5" />
        Score &gt; 80
      </button>

      {/* Divider */}
      <div className="h-6 w-px bg-slate-700" />

      {/* Result count */}
      <span className="text-xs text-slate-500 font-mono tabular-nums">
        {filteredCount} / {totalCount}
      </span>

      {/* Clear filters */}
      {hasActiveFilters && (
        <button
          onClick={clearFilters}
          className="inline-flex items-center gap-1 px-2 py-1 text-xs text-slate-500 hover:text-slate-300 transition-colors"
        >
          <X className="h-3 w-3" />
          Clear
        </button>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// TOAST NOTIFICATION
// ═══════════════════════════════════════════════════════════════════════════

interface ToastProps {
  toast: ToastState;
  onDismiss: (id: string) => void;
}

const Toast: FC<ToastProps> = ({ toast, onDismiss }) => {
  const icons = {
    loading: <Loader2 className="h-4 w-4 animate-spin text-blue-400" />,
    success: <Check className="h-4 w-4 text-emerald-400" />,
    error: <AlertCircle className="h-4 w-4 text-red-400" />,
  };

  const bgColors = {
    loading: 'bg-blue-500/10 border-blue-500/30',
    success: 'bg-emerald-500/10 border-emerald-500/30',
    error: 'bg-red-500/10 border-red-500/30',
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -10, scale: 0.95 }}
      className={cn(
        'flex items-center gap-3 px-4 py-3 rounded-lg border shadow-lg backdrop-blur-sm',
        bgColors[toast.type]
      )}
    >
      {icons[toast.type]}
      <span className="text-sm text-white">{toast.message}</span>
      {toast.type !== 'loading' && (
        <button
          onClick={() => onDismiss(toast.id)}
          className="ml-2 text-slate-500 hover:text-white transition-colors"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </motion.div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// SORTABLE HEADER
// ═══════════════════════════════════════════════════════════════════════════

interface SortableHeaderProps {
  label: string;
  field: SortField;
  currentSort: SortConfig | null;
  onSort: (field: SortField) => void;
  align?: 'left' | 'right';
  className?: string;
}

const SortableHeader: FC<SortableHeaderProps> = ({
  label,
  field,
  currentSort,
  onSort,
  align = 'left',
  className,
}) => {
  const isActive = currentSort?.field === field;
  const direction = isActive ? currentSort.direction : null;

  return (
    <th
      className={cn(
        'px-3 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider cursor-pointer select-none',
        'hover:text-slate-300 transition-colors',
        align === 'right' && 'text-right',
        className
      )}
      onClick={() => onSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <span className="inline-flex flex-col">
          <ChevronUp
            className={cn(
              'h-2.5 w-2.5 -mb-0.5',
              isActive && direction === 'asc' ? 'text-emerald-400' : 'text-slate-700'
            )}
          />
          <ChevronDown
            className={cn(
              'h-2.5 w-2.5 -mt-0.5',
              isActive && direction === 'desc' ? 'text-emerald-400' : 'text-slate-700'
            )}
          />
        </span>
      </span>
    </th>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// DATA TABLE ROW
// ═══════════════════════════════════════════════════════════════════════════

interface DataRowProps {
  row: RadarRow;
  isProcessing: boolean;
  onGeneratePacket: (judgmentId: string) => void;
}

const DataRow: FC<DataRowProps> = ({ row, isProcessing, onGeneratePacket }) => {
  return (
    <motion.tr
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors"
    >
      {/* Score */}
      <td className="px-3 py-2">
        <ScoreBadge score={row.collectabilityScore} />
      </td>

      {/* Plaintiff */}
      <td className="px-3 py-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-white truncate">{row.plaintiffName}</p>
          <p className="text-xs text-slate-500 truncate font-mono">{row.caseNumber}</p>
        </div>
      </td>

      {/* Defendant */}
      <td className="px-3 py-2">
        <p className="text-sm text-slate-300 truncate">{row.defendantName}</p>
      </td>

      {/* Amount */}
      <td className="px-3 py-2 text-right">
        <span className="text-sm font-mono font-semibold text-white tabular-nums">
          {formatCurrencyFull(row.judgmentAmount)}
        </span>
      </td>

      {/* Strategy */}
      <td className="px-3 py-2">
        <StrategyPill strategy={row.offerStrategy} />
      </td>

      {/* Action */}
      <td className="px-3 py-2">
        <button
          onClick={() => onGeneratePacket(row.id)}
          disabled={isProcessing}
          className={cn(
            'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all',
            isProcessing
              ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
              : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30'
          )}
        >
          {isProcessing ? (
            <>
              <Loader2 className="h-3 w-3 animate-spin" />
              Generating...
            </>
          ) : (
            <>
              <FileText className="h-3 w-3" />
              Generate Packet
            </>
          )}
        </button>
      </td>
    </motion.tr>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// SKELETON LOADER
// ═══════════════════════════════════════════════════════════════════════════

const SkeletonRow: FC = () => (
  <tr className="border-b border-slate-800/50">
    <td className="px-3 py-3">
      <div className="h-5 w-10 bg-slate-800 rounded animate-pulse" />
    </td>
    <td className="px-3 py-3">
      <div className="space-y-1.5">
        <div className="h-4 w-32 bg-slate-800 rounded animate-pulse" />
        <div className="h-3 w-24 bg-slate-800/50 rounded animate-pulse" />
      </div>
    </td>
    <td className="px-3 py-3">
      <div className="h-4 w-28 bg-slate-800 rounded animate-pulse" />
    </td>
    <td className="px-3 py-3 text-right">
      <div className="h-4 w-20 bg-slate-800 rounded animate-pulse ml-auto" />
    </td>
    <td className="px-3 py-3">
      <div className="h-5 w-14 bg-slate-800 rounded animate-pulse" />
    </td>
    <td className="px-3 py-3">
      <div className="h-7 w-28 bg-slate-800 rounded animate-pulse" />
    </td>
  </tr>
);

// ═══════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════════════════════════

const EnforcementActionCenter: FC = () => {
  // Local state for filters (controlled by toolbar)
  const [filters, setFilters] = useState<FilterState>({
    showOnlyEmployed: false,
    showOnlyBankAssets: false,
    minScore: 0,
  });

  // Convert FilterState to RadarFilters for the hook
  const radarFilters = useMemo(() => ({
    minScore: filters.minScore > 0 ? filters.minScore : undefined,
    onlyEmployed: filters.showOnlyEmployed,
    onlyBankAssets: filters.showOnlyBankAssets,
  }), [filters]);

  // Pass filters to the hook - server-side filtering
  const { data, status, isError, errorMessage, refetch } = useEnforcementRadar(radarFilters);
  const { generatePacket, isProcessing } = useEnforcementActions();

  const isLoading = status === 'loading' || status === 'idle';

  // Subscribe to global refresh
  useOnRefresh(() => refetch());

  const [sort, setSort] = useState<SortConfig | null>({
    field: 'collectabilityScore',
    direction: 'desc',
  });
  const [toasts, setToasts] = useState<ToastState[]>([]);

  // Toast helpers
  const addToast = useCallback((toast: Omit<ToastState, 'id'>) => {
    const id = `toast-${Date.now()}-${Math.random()}`;
    setToasts((prev) => [...prev, { ...toast, id }]);
    return id;
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const updateToast = useCallback((id: string, updates: Partial<ToastState>) => {
    setToasts((prev) =>
      prev.map((t) => (t.id === id ? { ...t, ...updates } : t))
    );
  }, []);

  // Handle packet generation
  const handleGeneratePacket = useCallback(
    async (judgmentId: string) => {
      // Find the row data for telemetry context
      const row = data?.find((r) => r.id === judgmentId);

      // Log telemetry for the packet generation click
      telemetry.enforcementGeneratePacketClicked({
        judgmentId,
        strategy: row?.offerStrategy,
        collectabilityScore: row?.collectabilityScore ?? undefined,
        judgmentAmount: row?.judgmentAmount,
      });

      const toastId = addToast({
        type: 'loading',
        message: 'Generating enforcement packet...',
      });

      try {
        await generatePacket({ judgmentId });
        updateToast(toastId, {
          type: 'success',
          message: 'Packet generated successfully!',
        });

        // Auto-dismiss success after 3s
        setTimeout(() => removeToast(toastId), 3000);
      } catch {
        updateToast(toastId, {
          type: 'error',
          message: 'Failed to generate packet. Please try again.',
        });

        // Auto-dismiss error after 5s
        setTimeout(() => removeToast(toastId), 5000);
      }
    },
    [data, generatePacket, addToast, updateToast, removeToast]
  );

  // Handle sort
  const handleSort = useCallback((field: SortField) => {
    setSort((prev) => {
      if (prev?.field === field) {
        return prev.direction === 'desc'
          ? { field, direction: 'asc' }
          : { field, direction: 'desc' };
      }
      return { field, direction: 'desc' };
    });
  }, []);

  // Filter and sort data
  // Note: Filters are now applied server-side via the hook.
  // We only do client-side sorting here.
  const rows = data ?? [];

  const sortedRows = useMemo(() => {
    if (!sort) return rows;

    return [...rows].sort((a, b) => {
      const multiplier = sort.direction === 'desc' ? -1 : 1;

      switch (sort.field) {
        case 'collectabilityScore':
          // Nulls last
          if (a.collectabilityScore === null && b.collectabilityScore === null) return 0;
          if (a.collectabilityScore === null) return 1;
          if (b.collectabilityScore === null) return -1;
          return (a.collectabilityScore - b.collectabilityScore) * multiplier;
        case 'judgmentAmount':
          return (a.judgmentAmount - b.judgmentAmount) * multiplier;
        case 'plaintiffName':
          return a.plaintiffName.localeCompare(b.plaintiffName) * multiplier;
        default:
          return 0;
      }
    });
  }, [rows, sort]);

  // KPIs
  const kpis = useMemo(() => computeRadarKPIs(rows), [rows]);

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Toast Container */}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        <AnimatePresence mode="popLayout">
          {toasts.map((toast) => (
            <Toast key={toast.id} toast={toast} onDismiss={removeToast} />
          ))}
        </AnimatePresence>
      </div>

      <div className="p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white font-mono tracking-tight flex items-center gap-3">
              <Target className="h-7 w-7 text-emerald-400" />
              ENFORCEMENT ACTION CENTER
            </h1>
            <p className="text-sm text-slate-500 mt-1">
              Generate enforcement packets for high-priority judgments
            </p>
          </div>
          <button
            onClick={() => refetch()}
            disabled={isLoading}
            className={cn(
              'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              'bg-slate-800 text-slate-300 border border-slate-700',
              'hover:bg-slate-700 hover:text-white',
              isLoading && 'opacity-50 cursor-not-allowed'
            )}
          >
            <RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />
            Refresh
          </button>
        </div>

        {/* KPI Strip */}
        <div className="grid grid-cols-5 gap-4">
          <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Total Cases</p>
            <p className="text-2xl font-bold font-mono text-white mt-1 tabular-nums">
              {kpis.totalCases}
            </p>
          </div>
          <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Buy Candidates</p>
            <p className="text-2xl font-bold font-mono text-purple-400 mt-1 tabular-nums">
              {kpis.buyCandidateCount}
            </p>
            <p className="text-xs text-slate-600 font-mono">{formatCurrency(kpis.buyCandidateValue)}</p>
          </div>
          <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Contingency</p>
            <p className="text-2xl font-bold font-mono text-blue-400 mt-1 tabular-nums">
              {kpis.contingencyCount}
            </p>
            <p className="text-xs text-slate-600 font-mono">{formatCurrency(kpis.contingencyValue)}</p>
          </div>
          <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Actionable Value</p>
            <p className="text-2xl font-bold font-mono text-emerald-400 mt-1 tabular-nums">
              {formatCurrency(kpis.totalActionableValue)}
            </p>
          </div>
          <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Avg Score</p>
            <p className="text-2xl font-bold font-mono text-white mt-1 tabular-nums">
              {kpis.avgScore !== null ? Math.round(kpis.avgScore) : '—'}
            </p>
          </div>
        </div>

        {/* Filter Toolbar */}
        <FilterToolbar
          filters={filters}
          onFilterChange={setFilters}
          totalCount={rows.length}
          filteredCount={sortedRows.length}
        />

        {/* Data Table */}
        <div className="bg-slate-900/30 border border-slate-800 rounded-lg overflow-hidden">
          {isError ? (
            <div className="p-8 text-center">
              <AlertCircle className="h-8 w-8 text-red-400 mx-auto mb-3" />
              <p className="text-red-400 font-medium">Failed to load data</p>
              <p className="text-sm text-slate-500 mt-1">{errorMessage}</p>
              <button
                onClick={() => refetch()}
                className="mt-4 px-4 py-2 bg-slate-800 text-white rounded-lg text-sm hover:bg-slate-700"
              >
                Try Again
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-slate-900/50 border-b border-slate-800">
                  <tr>
                    <SortableHeader
                      label="Score"
                      field="collectabilityScore"
                      currentSort={sort}
                      onSort={handleSort}
                      className="w-20"
                    />
                    <SortableHeader
                      label="Plaintiff"
                      field="plaintiffName"
                      currentSort={sort}
                      onSort={handleSort}
                    />
                    <th className="px-3 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider text-left">
                      Defendant
                    </th>
                    <SortableHeader
                      label="Amount"
                      field="judgmentAmount"
                      currentSort={sort}
                      onSort={handleSort}
                      align="right"
                    />
                    <th className="px-3 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider text-left">
                      Strategy
                    </th>
                    <th className="px-3 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider text-left w-36">
                      Action
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {isLoading ? (
                    // Skeleton loading
                    Array.from({ length: 10 }).map((_, i) => <SkeletonRow key={i} />)
                  ) : sortedRows.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-3 py-12 text-center">
                        <p className="text-slate-500">No cases match your filters</p>
                        <button
                          onClick={() =>
                            setFilters({
                              showOnlyEmployed: false,
                              showOnlyBankAssets: false,
                              minScore: 0,
                            })
                          }
                          className="mt-2 text-sm text-emerald-400 hover:underline"
                        >
                          Clear all filters
                        </button>
                      </td>
                    </tr>
                  ) : (
                    sortedRows.map((row) => (
                      <DataRow
                        key={row.id}
                        row={row}
                        isProcessing={isProcessing(row.id)}
                        onGeneratePacket={handleGeneratePacket}
                      />
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Footer Stats */}
        {!isLoading && sortedRows.length > 0 && (
          <div className="flex items-center justify-between text-xs text-slate-600">
            <span className="font-mono">
              Showing {sortedRows.length} of {rows.length} judgments
            </span>
            <span className="font-mono">
              Total filtered value: {formatCurrencyFull(sortedRows.reduce((sum, r) => sum + r.judgmentAmount, 0))}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

export default EnforcementActionCenter;
