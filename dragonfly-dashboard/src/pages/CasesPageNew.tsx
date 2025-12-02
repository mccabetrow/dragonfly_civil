/**
 * CasesPage - Browse and manage all cases
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Primary case management interface showing:
 * - Searchable, filterable case list with DataTable
 * - Slide-out drawer for case details
 * - Keyboard navigation support
 *
 * Architecture:
 * - useCasesTable handles data, filtering, selection
 * - CaseTable provides keyboard-navigable table
 * - CaseDetailDrawer shows case details on selection
 */

import { type FC, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Briefcase } from 'lucide-react';
import CaseTable from '../components/cases/CaseTable';
import CaseDetailDrawer from '../components/cases/CaseDetailDrawer';
import HelpTooltip from '../components/HelpTooltip';
import ZeroStateCard from '../components/ZeroStateCard';
import { PageHeader, Card, Button } from '../components/primitives';
import {
  useCasesTable,
  CASES_TIER_OPTIONS,
  type CasesTierFilter,
} from '../hooks/useCasesTable';

// ═══════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const CasesPage: FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const {
    displayRows,
    allRows,
    tierFilter,
    setTierFilter,
    searchTerm,
    setSearchTerm,
    columns,
    selectedCaseId,
    setSelectedCaseId,
    isLoading,
    error,
    status,
    totalCount,
    resetFilters,
  } = useCasesTable();

  // Auto-select case from URL param (e.g., ?caseId=xxx from Overview)
  useEffect(() => {
    const urlCaseId = searchParams.get('caseId');
    if (urlCaseId) {
      setSelectedCaseId(urlCaseId);
      // Clear the URL param after opening to keep URL clean
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSelectedCaseId, setSearchParams]);

  const hasData = allRows.length > 0;
  const hasFilters = tierFilter !== 'All' || searchTerm.trim() !== '';
  const filteredEmpty = hasData && displayRows.length === 0 && hasFilters;

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <PageHeader
        title="Cases"
        description="Every judgment we're working on is listed below. Use the search box to find a specific case, or click any row to see full details."
        icon={<Briefcase className="h-5 w-5" />}
      />

      {/* Main Table Section */}
      <Card padding="none" border="strong" hoverable>
        {/* Section Header with Filters */}
        <div className="flex flex-col gap-4 border-b border-slate-200 px-6 py-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">Browse Judgments</h3>
            <p className="mt-1 text-sm text-slate-500">
              Use the search box to find a specific case number. Press arrow keys to navigate, Enter to select.
            </p>
          </div>

          {/* Filter Controls */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-end sm:gap-4">
            {/* Tier Filter */}
            <div className="flex flex-col gap-2 sm:w-48">
              <label
                className="text-xs font-semibold uppercase tracking-wide text-slate-500"
                htmlFor="cases-tier-filter"
              >
                Tier filter
                <HelpTooltip text="Show only cases from a specific tier. Tier A has the highest chance of collecting." />
              </label>
              <select
                id="cases-tier-filter"
                value={tierFilter}
                onChange={(e) => setTierFilter(e.target.value as CasesTierFilter)}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm transition focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              >
                {CASES_TIER_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option === 'All' ? 'All tiers' : `Tier ${option}`}
                  </option>
                ))}
              </select>
            </div>

            {/* Search */}
            <div className="flex flex-col gap-2 sm:max-w-xs sm:flex-1">
              <label
                className="text-xs font-semibold uppercase tracking-wide text-slate-500"
                htmlFor="cases-search"
              >
                Search
                <HelpTooltip text="Enter a case number or part of one to find a specific judgment quickly." />
              </label>
              <input
                id="cases-search"
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
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Showing {displayRows.length.toLocaleString()} of {totalCount.toLocaleString()} cases
            {hasFilters && (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={resetFilters}
                  className="ml-3 text-blue-600"
                >
                  Clear filters
                </Button>
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
              title="No cases yet"
              description="Your first judgments will appear here once we import them from Simplicity. Check back soon!"
              actionLink="/help"
              actionLabel="Learn more"
            />
          </div>
        )}

        {/* Empty Filter Results */}
        {filteredEmpty && (
          <div className="px-6 pb-6">
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-center text-sm text-slate-600">
              No cases match your search. Try clearing the tier filter or search box.
            </div>
          </div>
        )}

        {/* Case Table */}
        {(isLoading || (status === 'ready' && displayRows.length > 0)) && (
          <div className="px-6 pb-6">
            {/* Keyboard navigation hint */}
            <div className="mb-3 flex items-center gap-2 text-xs text-slate-500">
              <kbd className="rounded border border-slate-200 bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">↑</kbd>
              <kbd className="rounded border border-slate-200 bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">↓</kbd>
              <span>to navigate rows</span>
              <span className="text-slate-300">·</span>
              <kbd className="rounded border border-slate-200 bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">Enter</kbd>
              <span>to open details</span>
            </div>
            <CaseTable
              rows={displayRows}
              columns={columns}
              loading={isLoading}
              error={status === 'error' ? error ?? undefined : undefined}
              selectedCaseId={selectedCaseId}
              onSelectCase={setSelectedCaseId}
              pageSize={25}
            />
          </div>
        )}
      </Card>

      {/* Case Detail Drawer */}
      <CaseDetailDrawer
        caseId={selectedCaseId}
        onClose={() => setSelectedCaseId(null)}
      />
    </div>
  );
};

export default CasesPage;
