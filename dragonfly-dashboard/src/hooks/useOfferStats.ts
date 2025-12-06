/**
 * useOfferStats
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Hook for fetching offer statistics via apiClient.
 * Returns aggregate funnel metrics for offers.
 */
import { useCallback, useEffect, useState } from 'react';
import { apiClient, AuthError, NotFoundError } from '../lib/apiClient';
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
  isAuthError: boolean;
  isNotFound: boolean;
  refetch: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// API RESPONSE
// ═══════════════════════════════════════════════════════════════════════════

interface ApiOfferStats {
  total_offers: number;
  accepted: number;
  rejected: number;
  negotiation: number;
  conversion_rate: number;
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useOfferStats(filters?: OfferStatsFilters): OfferStatsResult {
  const [data, setData] = useState<OfferStatsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthError, setIsAuthError] = useState(false);
  const [isNotFound, setIsNotFound] = useState(false);

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
    setIsAuthError(false);
    setIsNotFound(false);

    try {
      const params = new URLSearchParams();
      if (filters?.fromDate) params.set('from_date', filters.fromDate);
      if (filters?.toDate) params.set('to_date', filters.toDate);

      const queryString = params.toString();
      const url = `/api/v1/offers/stats${queryString ? `?${queryString}` : ''}`;

      const json = await apiClient.get<ApiOfferStats>(url);

      setData({
        totalOffers: json.total_offers,
        accepted: json.accepted,
        rejected: json.rejected,
        negotiation: json.negotiation,
        conversionRate: json.conversion_rate,
      });
    } catch (err) {
      if (err instanceof AuthError) {
        setIsAuthError(true);
        setError('Invalid API key – check environment variables.');
        console.error('[useOfferStats] Auth error:', err);
      } else if (err instanceof NotFoundError) {
        setIsNotFound(true);
        setData(null);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to fetch offer stats');
        console.error('[useOfferStats] Error:', err);
      }
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
    isAuthError,
    isNotFound,
    refetch: fetchData,
  };
}
