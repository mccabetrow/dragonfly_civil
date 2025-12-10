/**
 * usePortfolioExplorerData - Data hook for the Portfolio Explorer page
 *
 * Provides:
 * - Paginated judgment data with server-side filtering
 * - Total portfolio value for hero stat
 * - Loading/error states
 * - Pagination controls
 */

import { useState, useEffect, useCallback } from "react";
import { apiClient } from "../lib/apiClient";

// =============================================================================
// Types
// =============================================================================

export interface JudgmentRow {
  id: string;
  case_number: string | null;
  plaintiff_name: string;
  defendant_name: string;
  judgment_amount: number;
  collectability_score: number;
  status: string;
  county: string;
  judgment_date: string | null;
  tier: "A" | "B" | "C";
  tier_label: string;
}

export interface PortfolioFilters {
  search: string;
  status: string | null;
  minScore: number | null;
  county: string | null;
}

export interface PaginationState {
  page: number;
  limit: number;
  totalCount: number;
  totalPages: number;
}

export interface PortfolioExplorerData {
  judgments: JudgmentRow[];
  totalValue: number;
  pagination: PaginationState;
  filters: PortfolioFilters;
  loading: boolean;
  error: string | null;
  // Actions
  setPage: (page: number) => void;
  setLimit: (limit: number) => void;
  setFilters: (filters: Partial<PortfolioFilters>) => void;
  refresh: () => void;
}

interface PortfolioJudgmentsResponse {
  items: JudgmentRow[];
  total_count: number;
  total_value: number;
  page: number;
  limit: number;
  total_pages: number;
  timestamp: string;
}

// =============================================================================
// Hook Implementation
// =============================================================================

export function usePortfolioExplorerData(): PortfolioExplorerData {
  // State
  const [judgments, setJudgments] = useState<JudgmentRow[]>([]);
  const [totalValue, setTotalValue] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination state
  const [pagination, setPagination] = useState<PaginationState>({
    page: 1,
    limit: 50,
    totalCount: 0,
    totalPages: 1,
  });

  // Filter state
  const [filters, setFiltersState] = useState<PortfolioFilters>({
    search: "",
    status: null,
    minScore: null,
    county: null,
  });

  // Fetch data function
  const fetchJudgments = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // Build query params
      const params = new URLSearchParams();
      params.set("page", pagination.page.toString());
      params.set("limit", pagination.limit.toString());

      if (filters.search) {
        params.set("search", filters.search);
      }
      if (filters.status) {
        params.set("status", filters.status);
      }
      if (filters.minScore !== null) {
        params.set("min_score", filters.minScore.toString());
      }
      if (filters.county) {
        params.set("county", filters.county);
      }

      const response = await apiClient.get<PortfolioJudgmentsResponse>(
        `/api/v1/portfolio/judgments?${params.toString()}`
      );

      setJudgments(response.items);
      setTotalValue(response.total_value);
      setPagination((prev) => ({
        ...prev,
        totalCount: response.total_count,
        totalPages: response.total_pages,
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load judgments";
      setError(message);
      console.error("[usePortfolioExplorerData] Fetch error:", err);
    } finally {
      setLoading(false);
    }
  }, [pagination.page, pagination.limit, filters]);

  // Fetch on mount and when dependencies change
  useEffect(() => {
    fetchJudgments();
  }, [fetchJudgments]);

  // Actions
  const setPage = useCallback((page: number) => {
    setPagination((prev) => ({ ...prev, page: Math.max(1, page) }));
  }, []);

  const setLimit = useCallback((limit: number) => {
    setPagination((prev) => ({
      ...prev,
      limit: Math.max(1, Math.min(limit, 100)),
      page: 1, // Reset to first page when limit changes
    }));
  }, []);

  const setFilters = useCallback((newFilters: Partial<PortfolioFilters>) => {
    setFiltersState((prev) => ({ ...prev, ...newFilters }));
    setPagination((prev) => ({ ...prev, page: 1 })); // Reset to first page when filters change
  }, []);

  const refresh = useCallback(() => {
    fetchJudgments();
  }, [fetchJudgments]);

  return {
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
  };
}

export default usePortfolioExplorerData;
