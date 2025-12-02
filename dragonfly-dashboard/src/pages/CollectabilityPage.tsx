import React, { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { PostgrestError } from '@supabase/supabase-js';
import { supabaseClient } from '../lib/supabaseClient';
import HelpTooltip from '../components/HelpTooltip';
import ZeroStateCard from '../components/ZeroStateCard';

export type CollectabilityTier = 'A' | 'B' | 'C';

export interface CollectabilitySnapshot {
  case_id: string;
  case_number: string | null;
  judgment_amount: number | null;
  judgment_date: string | null;
  age_days: number | null;
  last_enriched_at: string | null;
  last_enrichment_status: string | null;
  collectability_tier: CollectabilityTier;
}

type FetchState = 'idle' | 'loading' | 'error' | 'ready';

type TierFilter = CollectabilityTier | 'All';

type SortColumn = 'judgment_amount' | 'age_days';

const PAGE_SIZE = 25;

const tierOptions: TierFilter[] = ['All', 'A', 'B', 'C'];

const CollectabilityPage: React.FC = () => {
  const [rows, setRows] = useState<CollectabilitySnapshot[]>([]);
  const [state, setState] = useState<FetchState>('idle');
  const [error, setError] = useState<PostgrestError | Error | null>(null);
  const [tierFilter, setTierFilter] = useState<TierFilter>('All');
  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState<SortColumn | null>(null);
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');

  useEffect(() => {
    let cancelled = false;

    async function loadCollectability() {
      setState('loading');
      setError(null);

      try {
        const { data, error: queryError } = await supabaseClient
          .from('v_collectability_snapshot')
          .select('*')
          .order('collectability_tier', { ascending: true })
          .order('judgment_amount', { ascending: false, nullsFirst: false });

        if (cancelled) {
          return;
        }

        if (queryError) {
          setError(queryError);
          setState('error');
          return;
        }

        setRows(data ?? []);
        setState('ready');
      } catch (exc) {
        if (cancelled) {
          return;
        }
        setError(exc instanceof Error ? exc : new Error('Unknown error fetching collectability data.'));
        setState('error');
      }
    }

    loadCollectability();

    return () => {
      cancelled = true;
    };
  }, []);

  const counts = useMemo(() => {
    const base = { A: 0, B: 0, C: 0 } as Record<CollectabilityTier, number>;
    for (const row of rows) {
      base[row.collectability_tier] += 1;
    }
    return base;
  }, [rows]);

  const filteredRows = useMemo(() => {
    const trimmed = searchTerm.trim().toLowerCase();
    return rows.filter((row) => {
      if (tierFilter !== 'All' && row.collectability_tier !== tierFilter) {
        return false;
      }
      if (!trimmed) {
        return true;
      }
      return (row.case_number ?? '').toLowerCase().includes(trimmed);
    });
  }, [rows, tierFilter, searchTerm]);

  useEffect(() => {
    setPage(1);
  }, [tierFilter, searchTerm]);

  const sortedRows = useMemo(() => {
    if (!sortBy) {
      return filteredRows;
    }

    const directionMultiplier = sortDirection === 'asc' ? 1 : -1;
    const fallback = sortDirection === 'asc' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY;

    const getValue = (entry: CollectabilitySnapshot): number | null => {
      const raw = entry[sortBy];
      return typeof raw === 'number' ? raw : null;
    };

    return [...filteredRows].sort((a, b) => {
      const aValue = getValue(a);
      const bValue = getValue(b);

      const aComparable = aValue ?? fallback;
      const bComparable = bValue ?? fallback;

      if (aComparable === bComparable) {
        return 0;
      }

      return aComparable > bComparable ? directionMultiplier : -directionMultiplier;
    });
  }, [filteredRows, sortBy, sortDirection]);

  const totalPages = Math.max(1, Math.ceil(sortedRows.length / PAGE_SIZE));

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  const paginatedRows = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return sortedRows.slice(start, start + PAGE_SIZE);
  }, [sortedRows, page]);

  const hasRows = sortedRows.length > 0;
  const startIndex = hasRows ? (page - 1) * PAGE_SIZE + 1 : 0;
  const endIndex = hasRows
    ? Math.min(sortedRows.length, startIndex + paginatedRows.length - 1)
    : 0;
  const rangeLabel = hasRows && paginatedRows.length > 0
    ? `${startIndex.toLocaleString()}\u2013${endIndex.toLocaleString()}`
    : '0';
  const filteredCountLabel = sortedRows.length.toLocaleString();
  const totalCountLabel = rows.length.toLocaleString();

  const loading = state === 'loading' || state === 'idle';
  const empty = state === 'ready' && filteredRows.length === 0;

  const handleSort = (column: SortColumn) => {
    setPage(1);
    if (sortBy === column) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortBy(column);
    setSortDirection('desc');
  };

  const handlePrevPage = () => {
    setPage((prev) => Math.max(1, prev - 1));
  };

  const handleNextPage = () => {
    setPage((prev) => Math.min(totalPages, prev + 1));
  };

  const canPrev = page > 1;
  const canNext = hasRows && page < totalPages;

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <p className="text-sm text-slate-600">
          This page shows how likely we are to collect on each judgment. Tier A cases are your best bets — focus your time there first.
        </p>
      </div>

      <section className="grid gap-6 md:grid-cols-3">
        <SummaryCard
          tier="A"
          value={counts.A}
          title="Tier A — Best Chances"
          description="These are your highest-value, most recent judgments. Call these plaintiffs first — they're most likely to result in collections."
          accentClass="bg-emerald-50"
          badgeClass="border border-emerald-500/30 bg-emerald-500/10 text-emerald-700"
        />
        <SummaryCard
          tier="B"
          value={counts.B}
          title="Tier B — Worth Pursuing"
          description="Good candidates for follow-up. Work these after you've contacted all your Tier A plaintiffs."
          accentClass="bg-amber-50"
          badgeClass="border border-amber-500/30 bg-amber-500/10 text-amber-700"
        />
        <SummaryCard
          tier="C"
          value={counts.C}
          title="Tier C — Lower Priority"
          description="Older or smaller judgments. Keep these on the back burner and check in occasionally."
          accentClass="bg-slate-100"
          badgeClass="border border-slate-500/30 bg-slate-500/10 text-slate-700"
        />
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col gap-4 border-b border-slate-200 px-6 py-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">All Judgments</h2>
            <p className="mt-1 text-sm text-slate-500">
              Browse and search through every judgment. Click column headers to sort.
            </p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-end sm:gap-4">
            <div className="flex flex-col gap-2 sm:w-48">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500" htmlFor="tier-filter">
                Tier filter
                <HelpTooltip text="Filter the list to show only cases in a specific tier. Tier A has the best collection chances, so start there." />
              </label>
              <select
                id="tier-filter"
                value={tierFilter}
                onChange={(event) => setTierFilter(event.target.value as TierFilter)}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              >
                {tierOptions.map((option) => (
                  <option key={option} value={option}>
                    {option === 'All' ? 'All tiers' : `Tier ${option}`}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-slate-400">
                A = best bets, B = worth pursuing, C = lower priority.
              </p>
            </div>
            <div className="flex flex-col gap-2 sm:max-w-xs sm:flex-1">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500" htmlFor="case-search">
                Search
                <HelpTooltip text="Type a case number to find a specific judgment. You can search partial numbers too." />
              </label>
              <input
                id="case-search"
                type="search"
                placeholder="Search by case number"
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              />
            </div>
          </div>
        </div>

        <div className="px-6 pb-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Showing {rangeLabel} of {filteredCountLabel} cases
          <span className="ml-1 text-[11px] normal-case text-slate-400">(total {totalCountLabel})</span>
        </div>

        {loading && <StatusMessage message="Loading your judgments…" tone="neutral" />}

        {state === 'error' && error && <StatusMessage message={error.message} tone="error" />}

        {state === 'ready' && rows.length === 0 && (
          <div className="px-6 pb-6">
            <ZeroStateCard
              title="No judgments yet"
              description="Once cases are imported into the system, they'll appear here sorted by collection priority. Check back soon!"
              actionLink="/help"
              actionLabel="Learn how this page works"
            />
          </div>
        )}

        {empty && rows.length > 0 && <StatusMessage message="No judgments match your search. Try clearing the filters or check back after the next import." tone="neutral" />}

        {!loading && !empty && state === 'ready' && (
          <div className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm text-slate-700">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <HeaderCell>Case Number</HeaderCell>
                    <HeaderCell>Tier</HeaderCell>
                    <SortableHeaderCell
                      label="Judgment Amount"
                      column="judgment_amount"
                      sortBy={sortBy}
                      sortDirection={sortDirection}
                      onClick={handleSort}
                    />
                    <SortableHeaderCell
                      label="Age (days)"
                      column="age_days"
                      sortBy={sortBy}
                      sortDirection={sortDirection}
                      onClick={handleSort}
                    />
                    <HeaderCell>Last Enrichment Status</HeaderCell>
                    <HeaderCell>Last Enriched At</HeaderCell>
                  </tr>
                </thead>
                <tbody>
                  {paginatedRows.map((row) => (
                    <tr key={row.case_id} className="border-b border-slate-100 bg-white transition hover:bg-slate-50">
                      <DataCell>{row.case_number ?? '—'}</DataCell>
                      <DataCell>
                        <span className={tierPillClass(row.collectability_tier)}>Tier {row.collectability_tier}</span>
                      </DataCell>
                      <DataCell>{formatCurrency(row.judgment_amount)}</DataCell>
                      <DataCell>{typeof row.age_days === 'number' ? row.age_days : '—'}</DataCell>
                      <DataCell>{row.last_enrichment_status ?? '—'}</DataCell>
                      <DataCell>{formatTimestamp(row.last_enriched_at)}</DataCell>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {!loading && hasRows && state === 'ready' && (
          <div className="border-t border-slate-100 px-6 py-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-sm text-slate-600">
                Page {page} of {totalPages}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handlePrevPage}
                  disabled={!canPrev}
                  className={`inline-flex items-center rounded-xl border px-3 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40 ${
                    canPrev
                      ? 'border-slate-300 bg-white text-slate-700 hover:bg-slate-100'
                      : 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400'
                  }`}
                >
                  Prev
                </button>
                <button
                  type="button"
                  onClick={handleNextPage}
                  disabled={!canNext}
                  className={`inline-flex items-center rounded-xl border px-3 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40 ${
                    canNext
                      ? 'border-slate-300 bg-white text-slate-700 hover:bg-slate-100'
                      : 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400'
                  }`}
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
};

export default CollectabilityPage;

function SummaryCard({
  tier,
  value,
  title,
  description,
  accentClass,
  badgeClass,
}: {
  tier: CollectabilityTier;
  value: number;
  title: string;
  description: string;
  accentClass: string;
  badgeClass: string;
}) {
  return (
    <article className={`rounded-2xl border border-slate-200 p-6 shadow-sm ${accentClass}`}>
      <div className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${badgeClass}`}>
        Tier {tier}
      </div>
      <p className="mt-4 text-4xl font-semibold text-slate-900">{value.toLocaleString()}</p>
      <h3 className="mt-3 text-sm font-semibold text-slate-700">{title}</h3>
      <p className="mt-2 text-sm text-slate-600">{description}</p>
    </article>
  );
}

function HeaderCell({ children }: { children: ReactNode }) {
  return <th className="px-4 py-3">{children}</th>;
}

function SortableHeaderCell({
  label,
  column,
  sortBy,
  sortDirection,
  onClick,
}: {
  label: string;
  column: SortColumn;
  sortBy: SortColumn | null;
  sortDirection: 'asc' | 'desc';
  onClick: (column: SortColumn) => void;
}) {
  const isActive = sortBy === column;
  const arrow = !isActive ? '↕' : sortDirection === 'asc' ? '↑' : '↓';

  return (
    <th className="px-4 py-3">
      <button
        type="button"
        onClick={() => onClick(column)}
        className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500 transition hover:text-slate-700 focus:outline-none focus-visible:rounded focus-visible:ring-2 focus-visible:ring-blue-500/40"
      >
        <span>{label}</span>
        <span aria-hidden="true" className={`text-[10px] leading-none ${isActive ? 'text-slate-700' : 'text-slate-300'}`}>
          {arrow}
        </span>
        <span className="sr-only">sort</span>
      </button>
    </th>
  );
}

function DataCell({ children }: { children: ReactNode }) {
  return <td className="px-4 py-3 align-middle text-sm text-slate-700">{children}</td>;
}

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

function formatCurrency(value: number | null): string {
  if (typeof value !== 'number') {
    return '—';
  }
  return currencyFormatter.format(value);
}

const timeFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeStyle: 'short',
});

function formatTimestamp(value: string | null): string {
  if (!value) {
    return '—';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return '—';
  }
  return timeFormatter.format(parsed);
}

function tierPillClass(tier: CollectabilityTier): string {
  switch (tier) {
    case 'A':
      return 'inline-flex items-center rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-700';
    case 'B':
      return 'inline-flex items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-xs font-semibold text-amber-700';
    case 'C':
    default:
      return 'inline-flex items-center rounded-full border border-slate-500/30 bg-slate-500/10 px-2.5 py-0.5 text-xs font-semibold text-slate-700';
  }
}

function StatusMessage({ message, tone }: { message: string; tone: 'neutral' | 'error' }) {
  if (tone === 'error') {
    return (
      <div className="px-6 pb-6">
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {message}
        </div>
      </div>
    );
  }

  return (
    <div className="px-6 pb-6">
      <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-center text-sm text-slate-600">
        {message}
      </div>
    </div>
  );
}
