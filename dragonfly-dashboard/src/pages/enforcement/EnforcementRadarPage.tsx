/**
 * EnforcementRadarPage
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Daily cockpit for enforcement operations.
 * Shows prioritized cases ranked by collectability + offer strategy.
 *
 * Layout inspired by high-frequency trading desks:
 * - KPI strip at top
 * - Filter bar
 * - Dense data table with colored badges
 * - Detail drawer for case inspection
 */
import React, { useMemo, useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Target,
  DollarSign,
  TrendingUp,
  Filter,
  RefreshCw,
  ArrowUpDown,
  Sparkles,
  AlertCircle,
  Download,
  Eye,
  ChevronUp,
  ChevronDown,
  Search,
  Loader2,
  HelpCircle,
  CheckCircle2,
  XCircle,
  Clock,
  Phone,
  Receipt,
} from 'lucide-react';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Button,
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerBody,
  DrawerSection,
} from '../../components/primitives';
import { EnrichmentHealth } from '../../components/ops/EnrichmentHealth';
import {
  Tooltip,
  TooltipProvider,
} from '../../components/primitives/Tooltip';
import {
  useEnforcementRadar,
  computeRadarKPIs,
  type OfferStrategy,
  type RadarRow,
} from '../../hooks/useEnforcementRadar';
import { useRefreshBus } from '../../context/RefreshContext';
import { cn } from '../../lib/design-tokens';
import {
  searchSimilarJudgments,
  buildJudgmentContext,
  type JudgmentSearchResult,
} from '../../lib/semanticSearchClient';
import { CaseDetailDrawerTabbed } from './CaseDetailDrawerTabbed';
import { useOfferStats } from '../../hooks/useOfferStats';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

type SortField = 'collectabilityScore' | 'judgmentAmount' | 'judgmentDate';
type SortDirection = 'asc' | 'desc';

interface SortConfig {
  field: SortField;
  direction: SortDirection;
}

// ═══════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

const STRATEGY_OPTIONS: { value: OfferStrategy | 'ALL'; label: string }[] = [
  { value: 'ALL', label: 'All Strategies' },
  { value: 'BUY_CANDIDATE', label: 'Buy Candidates' },
  { value: 'CONTINGENCY', label: 'Contingency' },
  { value: 'ENRICHMENT_PENDING', label: 'Pending Enrichment' },
  { value: 'LOW_PRIORITY', label: 'Low Priority' },
];

// ═══════════════════════════════════════════════════════════════════════════
// TOOLTIP CONTENT
// ═══════════════════════════════════════════════════════════════════════════

const SCORE_TOOLTIP = (
  <div className="max-w-xs space-y-1 text-left">
    <p className="font-medium">Collectability Score (0–100)</p>
    <p className="text-xs opacity-90">Predicts how likely we are to recover money.</p>
    <div className="pt-1 space-y-0.5 text-xs">
      <p>🟢 <strong>70–100:</strong> High confidence – great candidates</p>
      <p>🟡 <strong>40–69:</strong> Medium confidence – worth pursuing</p>
      <p>⚪ <strong>0–39:</strong> Low confidence – deprioritize</p>
      <p>— <strong>NULL:</strong> Not scored yet (pending enrichment)</p>
    </div>
  </div>
);

const STRATEGY_TOOLTIP = (
  <div className="max-w-xs space-y-1 text-left">
    <p className="font-medium">Offer Strategy</p>
    <p className="text-xs opacity-90">Tells you what action to take on each case.</p>
    <div className="pt-1 space-y-0.5 text-xs">
      <p>🟢 <strong>BUY:</strong> Call immediately & make a cash offer</p>
      <p>🟡 <strong>CONT:</strong> Offer contingency collection</p>
      <p>⚪ <strong>PEND:</strong> Wait for data enrichment</p>
      <p>🔴 <strong>LOW:</strong> Deprioritize, check back later</p>
    </div>
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// BADGE COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

interface ScoreBadgeProps {
  score: number | null;
  size?: 'sm' | 'md';
}

const ScoreBadge: React.FC<ScoreBadgeProps> = ({ score, size = 'sm' }) => {
  if (score === null) {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1 rounded-full font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
          size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm'
        )}
      >
        <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
        —
      </span>
    );
  }

  let colorClasses: string;
  if (score >= 70) {
    colorClasses = 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
  } else if (score >= 40) {
    colorClasses = 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
  } else {
    colorClasses = 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400';
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full font-semibold tabular-nums',
        colorClasses,
        size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm'
      )}
    >
      {score}
    </span>
  );
};

interface StrategyBadgeProps {
  strategy: OfferStrategy;
  size?: 'sm' | 'md';
}

const StrategyBadge: React.FC<StrategyBadgeProps> = ({ strategy, size = 'sm' }) => {
  const config: Record<OfferStrategy, { label: string; classes: string }> = {
    BUY_CANDIDATE: {
      label: size === 'sm' ? 'BUY' : 'Buy Candidate',
      classes: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
    },
    CONTINGENCY: {
      label: size === 'sm' ? 'CONT' : 'Contingency',
      classes: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    },
    ENRICHMENT_PENDING: {
      label: size === 'sm' ? 'PEND' : 'Pending',
      classes: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
    },
    LOW_PRIORITY: {
      label: size === 'sm' ? 'LOW' : 'Low Priority',
      classes: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
    },
  };

  const { label, classes } = config[strategy];

  return (
    <span
      className={cn(
        'inline-flex items-center rounded font-bold uppercase tracking-wide',
        classes,
        size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm'
      )}
    >
      {label}
    </span>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// KPI CARD
// ═══════════════════════════════════════════════════════════════════════════

interface KPICardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ElementType;
  iconColor?: string;
}

const KPICard: React.FC<KPICardProps> = ({
  title,
  value,
  subtitle,
  icon: Icon,
  iconColor = 'text-primary',
}) => (
  <Card className="relative overflow-hidden">
    <CardContent className="p-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-muted-foreground">{title}</p>
          <p className="mt-1 text-2xl font-bold tabular-nums">{value}</p>
          {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
        </div>
        <div className={cn('p-2 rounded-lg bg-muted/50', iconColor)}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </CardContent>
  </Card>
);

// ═══════════════════════════════════════════════════════════════════════════
// SORTABLE HEADER
// ═══════════════════════════════════════════════════════════════════════════

interface SortableHeaderProps {
  label: string;
  field: SortField;
  currentSort: SortConfig | null;
  onSort: (field: SortField) => void;
  align?: 'left' | 'center' | 'right';
  tooltip?: React.ReactNode;
}

const SortableHeader: React.FC<SortableHeaderProps> = ({
  label,
  field,
  currentSort,
  onSort,
  align = 'left',
  tooltip,
}) => {
  const isActive = currentSort?.field === field;
  const direction = isActive ? currentSort.direction : null;

  const headerContent = (
    <span className="inline-flex items-center gap-1">
      {label}
      {tooltip && (
        <HelpCircle className="h-3 w-3 text-muted-foreground/60 hover:text-muted-foreground" />
      )}
      <span className="inline-flex flex-col">
        <ChevronUp
          className={cn(
            'h-3 w-3 -mb-1',
            isActive && direction === 'asc' ? 'text-primary' : 'text-muted-foreground/40'
          )}
        />
        <ChevronDown
          className={cn(
            'h-3 w-3 -mt-1',
            isActive && direction === 'desc' ? 'text-primary' : 'text-muted-foreground/40'
          )}
        />
      </span>
    </span>
  );

  return (
    <th
      className={cn(
        'px-4 py-3 font-medium cursor-pointer hover:bg-muted/70 transition-colors select-none',
        align === 'right' && 'text-right',
        align === 'center' && 'text-center'
      )}
      onClick={() => onSort(field)}
    >
      {tooltip ? (
        <Tooltip content={tooltip} side="top" delayDuration={200}>
          <span>{headerContent}</span>
        </Tooltip>
      ) : (
        headerContent
      )}
    </th>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// HELP DRAWER
// ═══════════════════════════════════════════════════════════════════════════

interface HelpDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const HelpDrawer: React.FC<HelpDrawerProps> = ({ open, onOpenChange }) => (
  <Drawer open={open} onOpenChange={onOpenChange}>
    <DrawerContent side="right" size="md">
      <DrawerHeader>
        <DrawerTitle className="flex items-center gap-2">
          <HelpCircle className="h-5 w-5 text-primary" />
          How to Use This Page
        </DrawerTitle>
        <DrawerDescription>
          Your daily guide to the Enforcement Radar
        </DrawerDescription>
      </DrawerHeader>
      <DrawerBody>
        {/* What Is It */}
        <DrawerSection title="What Is the Radar?">
          <p className="text-sm text-muted-foreground leading-relaxed">
            The <strong>Enforcement Radar</strong> is your daily command center for identifying which judgments to pursue. 
            It ranks every active case by collectability and recommends an action strategy—so you know exactly 
            where to focus your time and capital.
          </p>
          <p className="text-sm text-muted-foreground leading-relaxed mt-2">
            Think of it as a "hot list" that answers: <em>"Which cases should I call today, and why?"</em>
          </p>
        </DrawerSection>

        {/* Morning Checklist */}
        <DrawerSection title="Morning Checklist ☀️">
          <div className="space-y-3">
            <div className="flex items-start gap-3">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
                <span className="text-xs font-bold text-primary">1</span>
              </div>
              <div>
                <p className="text-sm font-medium">Work Buy Candidates First</p>
                <p className="text-xs text-muted-foreground">
                  Filter to BUY_CANDIDATE → Sort by Score → Call top 5–10 plaintiffs
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
                <span className="text-xs font-bold text-primary">2</span>
              </div>
              <div>
                <p className="text-sm font-medium">Then Work Contingency Cases</p>
                <p className="text-xs text-muted-foreground">
                  Filter to CONTINGENCY → Sort by Amount → Pitch top 10–15 plaintiffs
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
                <span className="text-xs font-bold text-primary">3</span>
              </div>
              <div>
                <p className="text-sm font-medium">Check Enrichment Health</p>
                <p className="text-xs text-muted-foreground">
                  Glance at the widget in the top-right. Green = healthy. Red = alert engineering.
                </p>
              </div>
            </div>
          </div>
        </DrawerSection>

        {/* Strategy Guide */}
        <DrawerSection title="Offer Strategy Guide">
          <div className="space-y-2">
            <div className="flex items-center gap-2 p-2 rounded-lg bg-purple-50 dark:bg-purple-900/20">
              <CheckCircle2 className="h-4 w-4 text-purple-600 dark:text-purple-400" />
              <div>
                <p className="text-sm font-medium text-purple-700 dark:text-purple-300">BUY_CANDIDATE</p>
                <p className="text-xs text-purple-600/80 dark:text-purple-400/80">
                  High value + high score. Call immediately & make a cash offer.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 p-2 rounded-lg bg-blue-50 dark:bg-blue-900/20">
              <Phone className="h-4 w-4 text-blue-600 dark:text-blue-400" />
              <div>
                <p className="text-sm font-medium text-blue-700 dark:text-blue-300">CONTINGENCY</p>
                <p className="text-xs text-blue-600/80 dark:text-blue-400/80">
                  Decent odds, lower value. Offer to collect for a percentage.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 p-2 rounded-lg bg-yellow-50 dark:bg-yellow-900/20">
              <Clock className="h-4 w-4 text-yellow-600 dark:text-yellow-400" />
              <div>
                <p className="text-sm font-medium text-yellow-700 dark:text-yellow-300">ENRICHMENT_PENDING</p>
                <p className="text-xs text-yellow-600/80 dark:text-yellow-400/80">
                  Awaiting data enrichment. Wait for the system to score it.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 p-2 rounded-lg bg-gray-50 dark:bg-gray-800">
              <XCircle className="h-4 w-4 text-gray-500 dark:text-gray-400" />
              <div>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300">LOW_PRIORITY</p>
                <p className="text-xs text-gray-600/80 dark:text-gray-400/80">
                  Low recovery odds. Deprioritize and check back later.
                </p>
              </div>
            </div>
          </div>
        </DrawerSection>

        {/* Score Guide */}
        <DrawerSection title="Collectability Score">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">70–100</span>
              <span className="text-sm text-muted-foreground">High confidence – great candidates</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">40–69</span>
              <span className="text-sm text-muted-foreground">Medium confidence – worth pursuing</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">0–39</span>
              <span className="text-sm text-muted-foreground">Low confidence – deprioritize</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">—</span>
              <span className="text-sm text-muted-foreground">Not scored yet (pending enrichment)</span>
            </div>
          </div>
        </DrawerSection>

        {/* Quick Tips */}
        <DrawerSection title="Quick Tips">
          <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
            <li>Click any column header to sort the table</li>
            <li>Click a row to open the case detail drawer</li>
            <li>Use "Find Similar" to discover related cases</li>
            <li>Export CSV to share your filtered list</li>
          </ul>
        </DrawerSection>
      </DrawerBody>
    </DrawerContent>
  </Drawer>
);

// ═══════════════════════════════════════════════════════════════════════════
// SIMILAR JUDGMENTS DRAWER
// ═══════════════════════════════════════════════════════════════════════════

interface SimilarJudgmentsDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sourceRow: RadarRow | null;
  results: JudgmentSearchResult[];
  isLoading: boolean;
  error: string | null;
  formatCurrency: (value: number) => string;
}

const SimilarJudgmentsDrawer: React.FC<SimilarJudgmentsDrawerProps> = ({
  open,
  onOpenChange,
  sourceRow,
  results,
  isLoading,
  error,
  formatCurrency,
}) => (
  <Drawer open={open} onOpenChange={onOpenChange}>
    <DrawerContent side="right" size="md">
      <DrawerHeader>
        <DrawerTitle className="flex items-center gap-2">
          <Search className="h-5 w-5" />
          Similar Judgments
        </DrawerTitle>
        <DrawerDescription>
          {sourceRow
            ? `Cases similar to ${sourceRow.caseNumber}`
            : 'Finding similar cases...'}
        </DrawerDescription>
      </DrawerHeader>
      <DrawerBody>
        {/* Source Case Summary */}
        {sourceRow && (
          <DrawerSection title="Source Case">
            <div className="rounded-lg bg-muted/50 p-3 space-y-1">
              <p className="text-sm font-medium">{sourceRow.plaintiffName}</p>
              <p className="text-xs text-muted-foreground">
                vs {sourceRow.defendantName}
              </p>
              <p className="text-xs text-muted-foreground">
                {formatCurrency(sourceRow.judgmentAmount)} • {sourceRow.county ?? 'Unknown County'}
              </p>
            </div>
          </DrawerSection>
        )}

        {/* Loading State */}
        {isLoading && (
          <div className="flex flex-col items-center justify-center py-12">
            <Loader2 className="h-8 w-8 text-primary animate-spin mb-3" />
            <p className="text-sm text-muted-foreground">Searching for similar cases...</p>
          </div>
        )}

        {/* Error State */}
        {error && !isLoading && (
          <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-center">
            <AlertCircle className="h-6 w-6 text-destructive mx-auto mb-2" />
            <p className="text-sm text-destructive">{error}</p>
          </div>
        )}

        {/* Results */}
        {!isLoading && !error && results.length > 0 && (
          <DrawerSection title={`Top ${results.length} Similar Cases`}>
            <div className="space-y-3">
              {results.map((result, index) => (
                <div
                  key={result.id}
                  className="rounded-lg border p-3 hover:bg-muted/30 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-primary/10 text-primary text-xs font-bold">
                          {index + 1}
                        </span>
                        <span className="font-mono text-xs text-muted-foreground">
                          {result.case_number ?? '—'}
                        </span>
                      </div>
                      <p className="text-sm font-medium truncate">
                        {result.plaintiff_name ?? 'Unknown Plaintiff'}
                      </p>
                      <p className="text-xs text-muted-foreground truncate">
                        vs {result.defendant_name ?? 'Unknown Defendant'}
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-sm font-semibold tabular-nums">
                        {result.judgment_amount
                          ? formatCurrency(result.judgment_amount)
                          : '—'}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {result.county ?? '—'}
                      </p>
                    </div>
                  </div>
                  {/* Similarity score bar */}
                  <div className="mt-2 flex items-center gap-2">
                    <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full bg-primary rounded-full transition-all"
                        style={{ width: `${Math.round(result.score * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-muted-foreground tabular-nums w-10">
                      {Math.round(result.score * 100)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </DrawerSection>
        )}

        {/* No Results */}
        {!isLoading && !error && results.length === 0 && sourceRow && (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <Search className="h-8 w-8 text-muted-foreground/50 mb-3" />
            <p className="text-sm text-muted-foreground">No similar cases found</p>
            <p className="text-xs text-muted-foreground mt-1">
              Try adjusting the search or check if embeddings are enabled
            </p>
          </div>
        )}
      </DrawerBody>
    </DrawerContent>
  </Drawer>
);

// ═══════════════════════════════════════════════════════════════════════════
// CSV EXPORT
// ═══════════════════════════════════════════════════════════════════════════

function exportToCSV(rows: RadarRow[], filename: string) {
  const headers = [
    'Case Number',
    'Plaintiff',
    'Defendant',
    'Judgment Amount',
    'Collectability Score',
    'Offer Strategy',
    'Court',
    'County',
    'Judgment Date',
    'Created At',
  ];

  const csvRows = rows.map((row) => [
    row.caseNumber,
    `"${(row.plaintiffName ?? '').replace(/"/g, '""')}"`,
    `"${(row.defendantName ?? '').replace(/"/g, '""')}"`,
    row.judgmentAmount,
    row.collectabilityScore ?? '',
    row.offerStrategy,
    row.court ?? '',
    row.county ?? '',
    row.judgmentDate ?? '',
    row.createdAt,
  ]);

  const csvContent = [headers.join(','), ...csvRows.map((row) => row.join(','))].join('\n');

  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// ═══════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════════════════════════

const EnforcementRadarPage: React.FC = () => {
  const { triggerRefresh, isRefreshing } = useRefreshBus();

  // Offer stats for the KPI strip
  const { data: offerStats } = useOfferStats();

  // Filter state
  const [strategyFilter, setStrategyFilter] = useState<OfferStrategy | 'ALL'>('ALL');
  const [minScore, setMinScore] = useState<number>(0);
  const [minAmount, setMinAmount] = useState<string>('');

  // Sort state
  const [sortConfig, setSortConfig] = useState<SortConfig | null>(null);

  // Detail drawer state
  const [selectedRow, setSelectedRow] = useState<RadarRow | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Similar judgments drawer state
  const [similarDrawerOpen, setSimilarDrawerOpen] = useState(false);
  const [similarSourceRow, setSimilarSourceRow] = useState<RadarRow | null>(null);
  const [similarResults, setSimilarResults] = useState<JudgmentSearchResult[]>([]);
  const [similarLoading, setSimilarLoading] = useState(false);
  const [similarError, setSimilarError] = useState<string | null>(null);

  // Help drawer state
  const [helpDrawerOpen, setHelpDrawerOpen] = useState(false);

  // Fetch data with filters
  const { state } = useEnforcementRadar({
    strategy: strategyFilter,
    minScore: minScore > 0 ? minScore : undefined,
    minAmount: minAmount ? Number(minAmount) : undefined,
  });

  // Compute KPIs
  const kpis = useMemo(() => {
    if (state.status !== 'ready' || !state.data) {
      return null;
    }
    return computeRadarKPIs(state.data);
  }, [state]);

  // Sort rows
  const sortedRows = useMemo(() => {
    if (state.status !== 'ready' || !state.data) return [];
    const rows = [...state.data];

    if (!sortConfig) return rows;

    return rows.sort((a, b) => {
      const { field, direction } = sortConfig;
      const multiplier = direction === 'asc' ? 1 : -1;

      if (field === 'collectabilityScore') {
        const aVal = a.collectabilityScore ?? -1;
        const bVal = b.collectabilityScore ?? -1;
        return (aVal - bVal) * multiplier;
      }

      if (field === 'judgmentAmount') {
        return (a.judgmentAmount - b.judgmentAmount) * multiplier;
      }

      if (field === 'judgmentDate') {
        const aVal = a.judgmentDate ? new Date(a.judgmentDate).getTime() : 0;
        const bVal = b.judgmentDate ? new Date(b.judgmentDate).getTime() : 0;
        return (aVal - bVal) * multiplier;
      }

      return 0;
    });
  }, [state, sortConfig]);

  // Handle sort toggle
  const handleSort = useCallback((field: SortField) => {
    setSortConfig((prev) => {
      if (prev?.field === field) {
        // Toggle direction or clear
        if (prev.direction === 'asc') {
          return { field, direction: 'desc' };
        } else {
          return null; // Clear sort
        }
      }
      // New field, start with desc (highest first)
      return { field, direction: 'desc' };
    });
  }, []);

  // Handle row click
  const handleRowClick = useCallback((row: RadarRow) => {
    setSelectedRow(row);
    setDrawerOpen(true);
  }, []);

  // Handle find similar
  const handleFindSimilar = useCallback(async (row: RadarRow) => {
    setSimilarSourceRow(row);
    setSimilarResults([]);
    setSimilarError(null);
    setSimilarLoading(true);
    setSimilarDrawerOpen(true);

    const contextQuery = buildJudgmentContext({
      plaintiffName: row.plaintiffName,
      defendantName: row.defendantName,
      judgmentAmount: row.judgmentAmount,
      court: row.court,
      county: row.county,
      caseNumber: row.caseNumber,
    });

    const result = await searchSimilarJudgments(contextQuery, 5);

    setSimilarLoading(false);

    if (result.ok) {
      // Filter out the source row itself from results
      const filtered = result.data.results.filter(
        (r) => r.case_number !== row.caseNumber
      );
      setSimilarResults(filtered);
    } else {
      setSimilarError(result.error);
    }
  }, []);

  // Handle export
  const handleExport = useCallback(() => {
    const timestamp = new Date().toISOString().slice(0, 10);
    exportToCSV(sortedRows, `enforcement_radar_${timestamp}.csv`);
  }, [sortedRows]);

  const formatCurrency = (value: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '—';
    try {
      return new Date(dateStr).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: '2-digit',
      });
    } catch {
      return dateStr;
    }
  };

  // ─────────────────────────────────────────────────────────────────────────
  // LOADING STATE
  // ─────────────────────────────────────────────────────────────────────────

  if (state.status === 'loading' || state.status === 'idle') {
    return (
      <div className="space-y-6 p-6 animate-pulse">
        <div className="h-8 w-48 bg-muted rounded" />
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 bg-muted rounded-lg" />
          ))}
        </div>
        <div className="h-96 bg-muted rounded-lg" />
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // ERROR STATE
  // ─────────────────────────────────────────────────────────────────────────

  if (state.status === 'error') {
    return (
      <div className="p-6">
        <Card className="border-destructive/50">
          <CardContent className="p-6 text-center">
            <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
            <h3 className="text-lg font-semibold mb-2">Unable to Load Radar</h3>
            <p className="text-muted-foreground mb-4">{state.errorMessage}</p>
            <Button onClick={triggerRefresh}>Retry</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // DEMO LOCKED STATE
  // ─────────────────────────────────────────────────────────────────────────

  if (state.status === 'demo_locked') {
    return (
      <div className="p-6">
        <Card>
          <CardContent className="p-6 text-center">
            <Sparkles className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            <h3 className="text-lg font-semibold mb-2">Demo Mode</h3>
            <p className="text-muted-foreground">{state.lockMessage}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // READY STATE
  // ─────────────────────────────────────────────────────────────────────────

  return (
    <TooltipProvider>
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Target className="h-6 w-6 text-primary" />
            Enforcement Radar
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Prioritized cases ranked by collectability and offer strategy
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleExport}
            disabled={sortedRows.length === 0}
            className="gap-2"
          >
            <Download className="h-4 w-4" />
            Export CSV
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={triggerRefresh}
            disabled={isRefreshing}
            className="gap-2"
          >
            <RefreshCw className={cn('h-4 w-4', isRefreshing && 'animate-spin')} />
            Refresh
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setHelpDrawerOpen(true)}
            className="gap-2"
          >
            <HelpCircle className="h-4 w-4" />
            Help
          </Button>
        </div>
      </div>

      {/* KPI Strip */}
      {kpis && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="grid grid-cols-2 md:grid-cols-4 gap-4"
        >
          <KPICard
            title="Total Actionable Value"
            value={formatCurrency(kpis.totalActionableValue)}
            subtitle={`${kpis.buyCandidateCount + kpis.contingencyCount} cases`}
            icon={DollarSign}
            iconColor="text-green-600"
          />
          <KPICard
            title="Buy Candidates"
            value={kpis.buyCandidateCount}
            subtitle={formatCurrency(kpis.buyCandidateValue)}
            icon={TrendingUp}
            iconColor="text-purple-600"
          />
          <KPICard
            title="Contingency Ready"
            value={kpis.contingencyCount}
            subtitle={formatCurrency(kpis.contingencyValue)}
            icon={Target}
            iconColor="text-blue-600"
          />
          <KPICard
            title="Avg Collectability"
            value={kpis.avgScore !== null ? kpis.avgScore.toFixed(0) : '—'}
            subtitle={`${kpis.pendingCount} pending enrichment`}
            icon={Sparkles}
            iconColor="text-amber-600"
          />
        </motion.div>
      )}

      {/* Offer Stats KPI Strip */}
      {offerStats && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="grid grid-cols-2 md:grid-cols-4 gap-4"
        >
          <KPICard
            title="Total Offers"
            value={offerStats.totalOffers}
            subtitle="all time"
            icon={Receipt}
            iconColor="text-indigo-600"
          />
          <KPICard
            title="Accepted"
            value={offerStats.accepted}
            subtitle={`${(offerStats.conversionRate * 100).toFixed(1)}% rate`}
            icon={CheckCircle2}
            iconColor="text-green-600"
          />
          <KPICard
            title="In Negotiation"
            value={offerStats.negotiation}
            subtitle="active deals"
            icon={Clock}
            iconColor="text-amber-600"
          />
          <KPICard
            title="Rejected"
            value={offerStats.rejected}
            subtitle="closed out"
            icon={XCircle}
            iconColor="text-red-600"
          />
        </motion.div>
      )}

      {/* Filter Bar + Enrichment Health */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <Card className="lg:col-span-3">
          <CardContent className="p-4">
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-2">
                <Filter className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm font-medium">Filters:</span>
              </div>

              {/* Strategy dropdown */}
              <select
                value={strategyFilter}
                onChange={(e) => setStrategyFilter(e.target.value as OfferStrategy | 'ALL')}
                className="h-9 px-3 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {STRATEGY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>

              {/* Min Score slider */}
              <div className="flex items-center gap-2">
                <label className="text-sm text-muted-foreground">Min Score:</label>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={10}
                  value={minScore}
                  onChange={(e) => setMinScore(Number(e.target.value))}
                  className="w-24 accent-primary"
                />
                <span className="text-sm font-medium w-8 tabular-nums">{minScore}</span>
              </div>

              {/* Min Amount input */}
              <div className="flex items-center gap-2">
                <label className="text-sm text-muted-foreground">Min $:</label>
                <input
                  type="number"
                  placeholder="0"
                  value={minAmount}
                  onChange={(e) => setMinAmount(e.target.value)}
                  className="h-9 w-24 px-3 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring tabular-nums"
                />
              </div>

              {/* Clear button */}
              {(strategyFilter !== 'ALL' || minScore > 0 || minAmount) && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setStrategyFilter('ALL');
                    setMinScore(0);
                    setMinAmount('');
                  }}
                >
                  Clear
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Enrichment Health Widget */}
        <EnrichmentHealth className="lg:col-span-1" />
      </div>

      {/* Data Table */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center justify-between">
            <span>Radar Queue ({sortedRows.length} cases)</span>
            <ArrowUpDown className="h-4 w-4 text-muted-foreground" />
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50">
                <tr>
                  <th className="px-4 py-3 text-left font-medium">Case #</th>
                  <th className="px-4 py-3 text-left font-medium">Plaintiff</th>
                  <th className="px-4 py-3 text-left font-medium">Defendant</th>
                  <SortableHeader
                    label="Amount"
                    field="judgmentAmount"
                    currentSort={sortConfig}
                    onSort={handleSort}
                    align="right"
                  />
                  <SortableHeader
                    label="Score"
                    field="collectabilityScore"
                    currentSort={sortConfig}
                    onSort={handleSort}
                    align="center"
                    tooltip={SCORE_TOOLTIP}
                  />
                  <th className="px-4 py-3 text-center font-medium">
                    <Tooltip content={STRATEGY_TOOLTIP} side="top" delayDuration={200}>
                      <span className="inline-flex items-center gap-1 cursor-help">
                        Strategy
                        <HelpCircle className="h-3 w-3 text-muted-foreground/60 hover:text-muted-foreground" />
                      </span>
                    </Tooltip>
                  </th>
                  <th className="px-4 py-3 text-left font-medium">Court</th>
                  <SortableHeader
                    label="Date"
                    field="judgmentDate"
                    currentSort={sortConfig}
                    onSort={handleSort}
                    align="left"
                  />
                  <th className="px-4 py-3 text-center font-medium w-32">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {sortedRows.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-4 py-12 text-center text-muted-foreground">
                      No cases match the current filters.
                    </td>
                  </tr>
                ) : (
                  sortedRows.map((row) => (
                    <tr
                      key={row.id}
                      className="hover:bg-muted/30 transition-colors"
                    >
                      <td className="px-4 py-3 font-mono text-xs">{row.caseNumber}</td>
                      <td className="px-4 py-3 max-w-[180px] truncate" title={row.plaintiffName}>
                        {row.plaintiffName}
                      </td>
                      <td className="px-4 py-3 max-w-[180px] truncate" title={row.defendantName}>
                        {row.defendantName}
                      </td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums">
                        {formatCurrency(row.judgmentAmount)}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <ScoreBadge score={row.collectabilityScore} />
                      </td>
                      <td className="px-4 py-3 text-center">
                        <StrategyBadge strategy={row.offerStrategy} />
                      </td>
                      <td className="px-4 py-3 text-muted-foreground text-xs">
                        {row.court ?? '—'}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground text-xs tabular-nums">
                        {formatDate(row.judgmentDate)}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <div className="flex items-center justify-center gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleRowClick(row)}
                            className="h-7 px-2 text-xs gap-1"
                            title="View case details"
                          >
                            <Eye className="h-3 w-3" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleFindSimilar(row)}
                            className="h-7 px-2 text-xs gap-1"
                            title="Find similar cases"
                          >
                            <Search className="h-3 w-3" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Detail Drawer (CEO Cockpit with Tabs) */}
      {selectedRow && (
        <CaseDetailDrawerTabbed
          row={selectedRow}
          open={drawerOpen}
          onOpenChange={setDrawerOpen}
          formatCurrency={formatCurrency}
          formatDate={formatDate}
          onOfferCreated={() => {
            // Optionally refresh offer stats when an offer is created
          }}
        />
      )}

      {/* Similar Judgments Drawer */}
      <SimilarJudgmentsDrawer
        open={similarDrawerOpen}
        onOpenChange={setSimilarDrawerOpen}
        sourceRow={similarSourceRow}
        results={similarResults}
        isLoading={similarLoading}
        error={similarError}
        formatCurrency={formatCurrency}
      />

      {/* Help Drawer */}
      <HelpDrawer open={helpDrawerOpen} onOpenChange={setHelpDrawerOpen} />
    </div>
    </TooltipProvider>
  );
};

export default EnforcementRadarPage;
