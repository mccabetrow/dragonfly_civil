/**
 * useOfferStats
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Hook for fetching offer statistics via the backend API.
 * Returns aggregate funnel metrics for offers.
 */
import { useCallback, useEffect, useState } from 'react';
import { IS_DEMO_MODE } from '../lib/supabaseClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface OfferStatsData {
  totalOffers: number;
  accepted: number;
  rejected: number;
  negotiation: number;
  conversionRate: number;
}

export interface OfferStatsFilters {
  fromDate?: string;
  toDate?: string;
}

export interface OfferStatsResult {
  data: OfferStatsData | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════════════════════════════════════════

function getApiBaseUrl(): string {
  const envUrl = import.meta.env.VITE_API_BASE_URL;
  return envUrl || '';
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useOfferStats(filters?: OfferStatsFilters): OfferStatsResult {
  const [data, setData] = useState<OfferStatsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (IS_DEMO_MODE) {
      // Return mock data for demo mode
      setData({
        totalOffers: 127,
        accepted: 42,
        rejected: 31,
        negotiation: 54,
        conversionRate: 0.33,
      });
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const baseUrl = getApiBaseUrl();
      const params = new URLSearchParams();

      if (filters?.fromDate) {
        params.set('from_date', filters.fromDate);
      }
      if (filters?.toDate) {
        params.set('to_date', filters.toDate);
      }

      const queryString = params.toString();
      const url = `${baseUrl}/api/v1/offers/stats${queryString ? `?${queryString}` : ''}`;

      const response = await fetch(url);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        setError(errorData.detail || `API error: ${response.status}`);
        setData(null);
        return;
      }

      const json = await response.json();

      setData({
        totalOffers: json.total_offers,
        accepted: json.accepted,
        rejected: json.rejected,
        negotiation: json.negotiation,
        conversionRate: json.conversion_rate,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch offer stats');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [filters?.fromDate, filters?.toDate]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return {
    data,
    loading,
    error,
    refetch: fetchData,
  };
}
