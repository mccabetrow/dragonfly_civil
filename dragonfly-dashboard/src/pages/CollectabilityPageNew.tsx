/**
 * CollectabilityPage - Judgment collection priority dashboard
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Shows all judgments ranked by collectability tier (A/B/C).
 * Ops users can filter by tier, search by case number, and sort columns.
 *
 * Architecture:
 * - useCollectabilityTable handles all data, filtering, sorting, persistence
 * - DataTable provides industrial-grade table UX
 * - TierSummaryCards show distribution at a glance
 *
 * Key Features:
 * - Filter persistence (survives page refresh)
 * - Sticky headers on scroll
 * - Responsive design
 * - Skeleton loading states
 * - Clear error handling
 */

import { type FC } from 'react';
import DataTable from '../components/ui/DataTable';
import { TierBadge } from '../components/ui/Badge';
import HelpTooltip from '../components/HelpTooltip';
import ZeroStateCard from '../components/ZeroStateCard';
import {
  useCollectabilityTable,
  TIER_OPTIONS,
  type TierFilter,
  type CollectabilitySortKey,
} from '../hooks/useCollectabilityTable';

// ═══════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const CollectabilityPage: FC = () => {
  const {
    displayRows,
    allRows,
    tierFilter,
    setTierFilter,
    searchTerm,
    setSearchTerm,
    sortKey,
    sortDirection,
    handleSort,
    tierCounts,
    columns,
    isLoading,
    error,
    status,
    resetFilters,
  } = useCollectabilityTable();

  const hasData = allRows.length > 0;
  const hasFilters = tierFilter !== 'All' || searchTerm.trim() !== '';
  const filteredEmpty = hasData && displayRows.length === 0 && hasFilters;

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <header className="space-y-2">
        <p className="text-sm text-slate-600">
          This page ranks every judgment by how likely we are to collect. 
          Start with <strong>Tier A</strong> — those are your best bets. 
          Click a tier card below to filter the list.
        </p>
      </header>

      {/* Tier Summary Cards */}
      <section className="grid gap-6 md:grid-cols-3">
        <TierSummaryCard
          tier="A"
          count={tierCounts.A}
          title="Tier A — Best Chances"
          description="These are your highest-value, most recent judgments. Call these plaintiffs first — they're most likely to result in collections."
          isLoading={isLoading}
          isActive={tierFilter === 'A'}
          onClick={() => setTierFilter(tierFilter === 'A' ? 'All' : 'A')}
        />
        <TierSummaryCard
          tier="B"
          count={tierCounts.B}
          title="Tier B — Worth Pursuing"
          description="Good candidates for follow-up. Work these after you've contacted all your Tier A plaintiffs."
          isLoading={isLoading}
          isActive={tierFilter === 'B'}
          onClick={() => setTierFilter(tierFilter === 'B' ? 'All' : 'B')}
        />
        <TierSummaryCard
          tier="C"
          count={tierCounts.C}
          title="Tier C — Lower Priority"
          description="Older or smaller judgments. Keep these on the back burner and check in occasionally."
          isLoading={isLoading}
          isActive={tierFilter === 'C'}
          onClick={() => setTierFilter(tierFilter === 'C' ? 'All' : 'C')}
        />
      </section>

      {/* Main Data Table Section */}
      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        {/* Section Header with Filters */}
        <div className="flex flex-col gap-4 border-b border-slate-200 px-6 py-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">All Judgments</h2>
            <p className="mt-1 text-sm text-slate-500">
              Browse and search through every judgment. Click column headers to sort.
            </p>
          </div>

          {/* Filter Controls */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-end sm:gap-4">
            {/* Tier Filter */}
            <div className="flex flex-col gap-2 sm:w-48">
              <label
                className="text-xs font-semibold uppercase tracking-wide text-slate-500"
                htmlFor="tier-filter"
              >
                Tier filter
                <HelpTooltip text="Filter the list to show only cases in a specific tier. Tier A has the best collection chances, so start there." />
              </label>
              <select
                id="tier-filter"
                value={tierFilter}
                onChange={(e) => setTierFilter(e.target.value as TierFilter)}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm transition focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              >
                {TIER_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option === 'All' ? 'All tiers' : `Tier ${option}`}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-slate-400">
                A = best bets, B = worth pursuing, C = lower priority.
              </p>
            </div>

            {/* Search */}
            <div className="flex flex-col gap-2 sm:max-w-xs sm:flex-1">
              <label
                className="text-xs font-semibold uppercase tracking-wide text-slate-500"
                htmlFor="case-search"
              >
                Search
                <HelpTooltip text="Type a case number to find a specific judgment. You can search partial numbers too." />
              </label>
              <input
                id="case-search"
                type="search"
                placeholder="Search by case number"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm transition focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              />
            </div>
          </div>
        </div>

        {/* Results Count & Filter Status */}
        <div className="flex items-center justify-between px-6 pb-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Showing {displayRows.length.toLocaleString()} of {allRows.length.toLocaleString()} cases
            {hasFilters && (
              <>
                <button
                  type="button"
                  onClick={resetFilters}
                  className="ml-3 text-blue-600 normal-case hover:text-blue-700 hover:underline"
                >
                  Clear filters
                </button>
                <span className="ml-2 text-slate-400 normal-case" title="Filters persist across page refreshes">
                  (saved)
                </span>
              </>
            )}
          </div>
        </div>

        {/* Error State */}
        {status === 'error' && error && (
          <div className="px-6 pb-6">
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          </div>
        )}

        {/* Zero State (no data at all) */}
        {status === 'ready' && allRows.length === 0 && (
          <div className="px-6 pb-6">
            <ZeroStateCard
              title="No judgments yet"
              description="Once cases are imported into the system, they'll appear here sorted by collection priority. Check back soon!"
              actionLink="/help"
              actionLabel="Learn how this page works"
            />
          </div>
        )}

        {/* Empty Filter Results */}
        {filteredEmpty && (
          <div className="px-6 pb-6">
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-center text-sm text-slate-600">
              No judgments match your search. Try clearing the filters or check back after the next import.
            </div>
          </div>
        )}

        {/* Data Table */}
        {(isLoading || (status === 'ready' && displayRows.length > 0)) && (
          <div className="px-6 pb-6">
            {/* Inline tip for power users */}
            <div className="mb-3 flex items-center gap-1.5 text-xs text-slate-500">
              <span className="inline-flex h-4 w-4 items-center justify-center rounded bg-slate-100 text-[10px] font-semibold text-slate-400">💡</span>
              <span>Sort by <strong className="font-medium text-slate-600">Judgment Amount</strong> to see your biggest opportunities first.</span>
            </div>
            <DataTable
              data={displayRows}
              columns={columns}
              keyExtractor={(row) => row.case_id}
              loading={isLoading}
              error={undefined}
              pageSize={25}
              showPagination
              defaultSortKey={sortKey}
              defaultSortDirection={sortDirection}
              onSort={(key) => handleSort(key as CollectabilitySortKey)}
              stickyHeader
              emptyTitle="No matching judgments"
              emptyDescription="Try adjusting your filters to see more results."
            />
          </div>
        )}
      </section>
    </div>
  );
};

export default CollectabilityPage;

// ═══════════════════════════════════════════════════════════════════════════
// TIER SUMMARY CARD
// ═══════════════════════════════════════════════════════════════════════════

interface TierSummaryCardProps {
  tier: 'A' | 'B' | 'C';
  count: number;
  title: string;
  description: string;
  isLoading: boolean;
  isActive: boolean;
  onClick: () => void;
}

const tierAccentClasses: Record<'A' | 'B' | 'C', string> = {
  A: 'bg-emerald-50 border-emerald-200 hover:border-emerald-400',
  B: 'bg-amber-50 border-amber-200 hover:border-amber-400',
  C: 'bg-slate-50 border-slate-200 hover:border-slate-400',
};

const tierActiveClasses: Record<'A' | 'B' | 'C', string> = {
  A: 'ring-2 ring-emerald-500 border-emerald-500',
  B: 'ring-2 ring-amber-500 border-amber-500',
  C: 'ring-2 ring-slate-500 border-slate-500',
};

const TierSummaryCard: FC<TierSummaryCardProps> = ({
  tier,
  count,
  title,
  description,
  isLoading,
  isActive,
  onClick,
}) => {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`
        group rounded-2xl border p-6 text-left shadow-sm transition-all cursor-pointer
        ${tierAccentClasses[tier]}
        ${isActive ? tierActiveClasses[tier] : ''}
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
        hover:shadow-md hover:-translate-y-0.5
      `}
      aria-pressed={isActive}
      title={isActive ? 'Click to show all tiers' : `Click to filter to Tier ${tier} only`}
    >
      <TierBadge tier={tier} size="sm" />

      <div className="mt-4">
        {isLoading ? (
          <div className="h-10 w-20 animate-pulse rounded-lg bg-slate-200" />
        ) : (
          <p className="text-4xl font-semibold text-slate-900 tabular-nums">
            {count.toLocaleString()}
          </p>
        )}
      </div>

      <h3 className="mt-3 text-sm font-semibold text-slate-700">{title}</h3>
      <p className="mt-2 text-sm text-slate-600">{description}</p>

      {isActive && (
        <p className="mt-3 text-xs font-medium text-slate-500">
          Click again to show all tiers
        </p>
      )}
    </button>
  );
};
