/**
 * Portfolio Explorer Page
 *
 * Dense financial data grid for browsing all judgments.
 * Features:
 * - Server-side pagination
 * - Search by case number, plaintiff, defendant
 * - Filter by status, tier, county
 * - Hero stat: Total Portfolio Value
 */

import React, { useState, useMemo } from "react";
import {
  Search,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  DollarSign,
  Filter,
  X,
} from "lucide-react";
import { usePortfolioExplorerData } from "../hooks/usePortfolioExplorerData";
import type { JudgmentRow } from "../hooks/usePortfolioExplorerData";

// =============================================================================
// Helper Functions
// =============================================================================

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

function formatCurrencyCompact(amount: number): string {
  if (amount >= 1_000_000) {
    return `$${(amount / 1_000_000).toFixed(1)}M`;
  }
  if (amount >= 1_000) {
    return `$${(amount / 1_000).toFixed(0)}K`;
  }
  return formatCurrency(amount);
}

function getTierBadgeClass(tier: string): string {
  switch (tier) {
    case "A":
      return "bg-emerald-100 text-emerald-800 border-emerald-200";
    case "B":
      return "bg-blue-100 text-blue-800 border-blue-200";
    case "C":
      return "bg-gray-100 text-gray-800 border-gray-200";
    default:
      return "bg-gray-100 text-gray-600 border-gray-200";
  }
}

function getStatusBadgeClass(status: string): string {
  const statusLower = status.toLowerCase();
  if (statusLower === "active" || statusLower === "collecting") {
    return "bg-green-100 text-green-800";
  }
  if (statusLower === "pending" || statusLower === "new") {
    return "bg-yellow-100 text-yellow-800";
  }
  if (statusLower === "closed" || statusLower === "complete") {
    return "bg-gray-100 text-gray-600";
  }
  return "bg-blue-100 text-blue-800";
}

// =============================================================================
// Sub-Components
// =============================================================================

interface HeroStatProps {
  value: number;
  loading: boolean;
}

function HeroStat({ value, loading }: HeroStatProps) {
  return (
    <div className="bg-gradient-to-br from-blue-600 to-blue-800 rounded-xl p-6 text-white shadow-lg">
      <div className="flex items-center gap-3 mb-2">
        <div className="p-2 bg-white/20 rounded-lg">
          <DollarSign className="w-6 h-6" />
        </div>
        <span className="text-blue-100 text-sm font-medium">Total Portfolio Value</span>
      </div>
      <div className="text-3xl font-bold">
        {loading ? (
          <div className="h-9 w-40 bg-white/20 rounded animate-pulse" />
        ) : (
          formatCurrencyCompact(value)
        )}
      </div>
    </div>
  );
}

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}

function SearchBar({ value, onChange, placeholder = "Search..." }: SearchBarProps) {
  return (
    <div className="relative">
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full pl-10 pr-4 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
      />
      {value && (
        <button
          onClick={() => onChange("")}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
        >
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  );
}

interface FilterDropdownProps {
  label: string;
  value: string | null;
  options: { value: string; label: string }[];
  onChange: (value: string | null) => void;
}

function FilterDropdown({ label, value, options, onChange }: FilterDropdownProps) {
  return (
    <div className="relative">
      <select
        value={value || ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="appearance-none px-3 py-2 pr-8 border border-gray-200 rounded-lg bg-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-gray-700"
      >
        <option value="">{label}</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <Filter className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
    </div>
  );
}

interface PaginationControlsProps {
  page: number;
  totalPages: number;
  totalCount: number;
  limit: number;
  onPageChange: (page: number) => void;
  onLimitChange: (limit: number) => void;
  loading: boolean;
}

function PaginationControls({
  page,
  totalPages,
  totalCount,
  limit,
  onPageChange,
  onLimitChange,
  loading,
}: PaginationControlsProps) {
  const start = (page - 1) * limit + 1;
  const end = Math.min(page * limit, totalCount);

  return (
    <div className="flex items-center justify-between border-t border-gray-200 bg-gray-50 px-4 py-3 rounded-b-lg">
      <div className="text-sm text-gray-600">
        {loading ? (
          <span className="text-gray-400">Loading...</span>
        ) : totalCount > 0 ? (
          <span>
            Showing <strong>{start}</strong>–<strong>{end}</strong> of{" "}
            <strong>{totalCount.toLocaleString()}</strong>
          </span>
        ) : (
          <span>No results</span>
        )}
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-600">Per page:</label>
          <select
            value={limit}
            onChange={(e) => onLimitChange(Number(e.target.value))}
            className="border border-gray-200 rounded px-2 py-1 text-sm"
          >
            {[25, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1 || loading}
            className="p-1 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
          <span className="px-3 text-sm text-gray-600">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages || loading}
            className="p-1 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <ChevronRight className="w-5 h-5" />
          </button>
        </div>
      </div>
    </div>
  );
}

interface JudgmentTableProps {
  judgments: JudgmentRow[];
  loading: boolean;
}

function JudgmentTable({ judgments, loading }: JudgmentTableProps) {
  if (loading && judgments.length === 0) {
    return (
      <div className="p-8 text-center text-gray-500">
        <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
        <p>Loading judgments...</p>
      </div>
    );
  }

  if (judgments.length === 0) {
    return (
      <div className="p-8 text-center text-gray-500">
        <p className="text-lg">No judgments found</p>
        <p className="text-sm mt-1">Try adjusting your search or filters</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-left">
          <tr>
            <th className="px-4 py-3 font-medium text-gray-600">Case #</th>
            <th className="px-4 py-3 font-medium text-gray-600">Plaintiff</th>
            <th className="px-4 py-3 font-medium text-gray-600">Defendant</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-right">Amount</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-center">Score</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-center">Tier</th>
            <th className="px-4 py-3 font-medium text-gray-600">Status</th>
            <th className="px-4 py-3 font-medium text-gray-600">County</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {judgments.map((j) => (
            <tr
              key={j.id}
              className="hover:bg-blue-50/50 transition-colors cursor-pointer"
            >
              <td className="px-4 py-3 font-mono text-xs text-gray-700">
                {j.case_number || "—"}
              </td>
              <td className="px-4 py-3 text-gray-900 font-medium max-w-[200px] truncate">
                {j.plaintiff_name}
              </td>
              <td className="px-4 py-3 text-gray-700 max-w-[200px] truncate">
                {j.defendant_name}
              </td>
              <td className="px-4 py-3 text-right font-medium text-gray-900">
                {formatCurrency(j.judgment_amount)}
              </td>
              <td className="px-4 py-3 text-center">
                <span
                  className={`inline-block w-10 text-center font-medium ${
                    j.collectability_score >= 80
                      ? "text-emerald-700"
                      : j.collectability_score >= 50
                      ? "text-blue-700"
                      : "text-gray-500"
                  }`}
                >
                  {j.collectability_score}
                </span>
              </td>
              <td className="px-4 py-3 text-center">
                <span
                  className={`inline-block px-2 py-0.5 text-xs font-semibold rounded border ${getTierBadgeClass(
                    j.tier
                  )}`}
                >
                  {j.tier}
                </span>
              </td>
              <td className="px-4 py-3">
                <span
                  className={`inline-block px-2 py-0.5 text-xs rounded ${getStatusBadgeClass(
                    j.status
                  )}`}
                >
                  {j.status}
                </span>
              </td>
              <td className="px-4 py-3 text-gray-600 text-sm">{j.county}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// =============================================================================
// Main Component
// =============================================================================

export function PortfolioExplorerPage() {
  const {
    judgments,
    totalValue,
    pagination,
    filters,
    loading,
    error,
    setPage,
    setLimit,
    setFilters,
    refresh,
  } = usePortfolioExplorerData();

  // Local search state for debouncing
  const [searchInput, setSearchInput] = useState(filters.search);

  // Debounce search input
  React.useEffect(() => {
    const timer = setTimeout(() => {
      if (searchInput !== filters.search) {
        setFilters({ search: searchInput });
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput, filters.search, setFilters]);

  // Status options (could come from API in future)
  const statusOptions = useMemo(
    () => [
      { value: "active", label: "Active" },
      { value: "pending", label: "Pending" },
      { value: "collecting", label: "Collecting" },
      { value: "closed", label: "Closed" },
    ],
    []
  );

  // Tier filter options
  const tierOptions = useMemo(
    () => [
      { value: "80", label: "Tier A (80+)" },
      { value: "50", label: "Tier B+ (50+)" },
    ],
    []
  );

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Page Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-7xl mx-auto">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Portfolio Explorer</h1>
              <p className="text-sm text-gray-500 mt-1">
                Browse and search all judgments in your portfolio
              </p>
            </div>
            <button
              onClick={refresh}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 text-sm font-medium text-gray-700 disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">
        {/* Hero Stat */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <HeroStat value={totalValue} loading={loading} />
          
          {/* Quick Stats */}
          <div className="bg-white rounded-xl p-4 border border-gray-200 flex items-center gap-4">
            <div className="p-2 bg-emerald-100 rounded-lg">
              <span className="text-emerald-700 font-bold text-lg">A</span>
            </div>
            <div>
              <div className="text-sm text-gray-500">Tier A Judgments</div>
              <div className="text-xl font-bold text-gray-900">
                {loading ? "—" : judgments.filter((j) => j.tier === "A").length}
              </div>
            </div>
          </div>

          <div className="bg-white rounded-xl p-4 border border-gray-200 flex items-center gap-4">
            <div className="p-2 bg-blue-100 rounded-lg">
              <span className="text-blue-700 font-bold text-lg">
                {pagination.totalCount.toLocaleString()}
              </span>
            </div>
            <div>
              <div className="text-sm text-gray-500">Total Judgments</div>
              <div className="text-xl font-bold text-gray-900">
                {loading ? "—" : `${pagination.totalPages} pages`}
              </div>
            </div>
          </div>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
            <strong>Error:</strong> {error}
          </div>
        )}

        {/* Filters */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex-1 min-w-[250px]">
              <SearchBar
                value={searchInput}
                onChange={setSearchInput}
                placeholder="Search case #, plaintiff, or defendant..."
              />
            </div>

            <FilterDropdown
              label="All Statuses"
              value={filters.status}
              options={statusOptions}
              onChange={(value) => setFilters({ status: value })}
            />

            <FilterDropdown
              label="All Tiers"
              value={filters.minScore?.toString() || null}
              options={tierOptions}
              onChange={(value) =>
                setFilters({ minScore: value ? parseInt(value) : null })
              }
            />

            {(filters.search || filters.status || filters.minScore) && (
              <button
                onClick={() => {
                  setSearchInput("");
                  setFilters({ search: "", status: null, minScore: null, county: null });
                }}
                className="text-sm text-blue-600 hover:text-blue-800 font-medium"
              >
                Clear filters
              </button>
            )}
          </div>
        </div>

        {/* Data Table */}
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <JudgmentTable judgments={judgments} loading={loading} />
          <PaginationControls
            page={pagination.page}
            totalPages={pagination.totalPages}
            totalCount={pagination.totalCount}
            limit={pagination.limit}
            onPageChange={setPage}
            onLimitChange={setLimit}
            loading={loading}
          />
        </div>
      </div>
    </div>
  );
}

export default PortfolioExplorerPage;
