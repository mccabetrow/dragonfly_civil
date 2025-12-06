/**
 * useOffers
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Hook for creating offers and fetching offer history for a judgment.
 * Uses unified apiClient for all API calls.
 */
import { useCallback, useEffect, useState } from 'react';
import { apiClient, AuthError, NotFoundError, ApiError } from '../lib/apiClient';
import { IS_DEMO_MODE } from '../lib/supabaseClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface Offer {
  id: string;
  judgmentId: number;
  offerAmount: number;
  offerType: 'purchase' | 'contingency';
  status: 'offered' | 'accepted' | 'rejected' | 'negotiation' | 'expired';
  operatorNotes: string;
  createdAt: string;
}

export interface CreateOfferPayload {
  judgment_id: number;
  offer_amount: number;
  offer_type: 'purchase' | 'contingency';
  operator_notes?: string;
}

export type CreateOfferResult =
  | { ok: true; offer: Offer }
  | { ok: false; error: string };

export interface OffersResult {
  offers: Offer[];
  loading: boolean;
  error: string | null;
  isAuthError: boolean;
  isNotFound: boolean;
  createOffer: (payload: CreateOfferPayload) => Promise<CreateOfferResult>;
  refetch: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// API RESPONSE TYPES
// ═══════════════════════════════════════════════════════════════════════════

interface ApiOffer {
  id: string;
  judgment_id: number;
  offer_amount: number;
  offer_type: 'purchase' | 'contingency';
  status: Offer['status'];
  operator_notes?: string;
  created_at: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useOffers(judgmentId: number | null): OffersResult {
  const [offers, setOffers] = useState<Offer[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthError, setIsAuthError] = useState(false);
  const [isNotFound, setIsNotFound] = useState(false);

  const fetchOffers = useCallback(async () => {
    if (!judgmentId) {
      setOffers([]);
      setError(null);
      setIsAuthError(false);
      setIsNotFound(false);
      return;
    }

    if (IS_DEMO_MODE) {
      // Return mock data for demo mode
      setOffers([
        {
          id: 'demo-offer-1',
          judgmentId,
          offerAmount: 15000,
          offerType: 'purchase',
          status: 'offered',
          operatorNotes: 'Initial offer',
          createdAt: new Date().toISOString(),
        },
      ]);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    setIsAuthError(false);
    setIsNotFound(false);

    try {
      const data = await apiClient.get<ApiOffer[] | { offers: ApiOffer[] }>(
        `/api/v1/offers?judgment_id=${judgmentId}`
      );

      const offersList = Array.isArray(data) ? data : data.offers || [];
      setOffers(
        offersList.map((o) => ({
          id: o.id,
          judgmentId: o.judgment_id,
          offerAmount: o.offer_amount,
          offerType: o.offer_type,
          status: o.status,
          operatorNotes: o.operator_notes || '',
          createdAt: o.created_at,
        }))
      );
    } catch (err) {
      if (err instanceof AuthError) {
        setIsAuthError(true);
        setError('Invalid API key – check console environment variables.');
        console.error('[useOffers] Auth error:', err);
      } else if (err instanceof NotFoundError) {
        // 404 means no offers yet - that's fine
        setIsNotFound(true);
        setOffers([]);
      } else if (err instanceof ApiError) {
        setError(`API error: ${err.status}`);
        console.error('[useOffers] API error:', err);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to fetch offers');
        console.error('[useOffers] Error:', err);
      }
      setOffers([]);
    } finally {
      setLoading(false);
    }
  }, [judgmentId]);

  const createOffer = useCallback(
    async (payload: CreateOfferPayload): Promise<CreateOfferResult> => {
      if (IS_DEMO_MODE) {
        const newOffer: Offer = {
          id: `demo-offer-${Date.now()}`,
          judgmentId: payload.judgment_id,
          offerAmount: payload.offer_amount,
          offerType: payload.offer_type,
          status: 'offered',
          operatorNotes: payload.operator_notes || '',
          createdAt: new Date().toISOString(),
        };
        setOffers((prev) => [newOffer, ...prev]);
        return { ok: true, offer: newOffer };
      }

      try {
        const json = await apiClient.post<ApiOffer>('/api/v1/offers', payload);

        const offer: Offer = {
          id: json.id,
          judgmentId: json.judgment_id,
          offerAmount: json.offer_amount,
          offerType: json.offer_type,
          status: json.status,
          operatorNotes: json.operator_notes || '',
          createdAt: json.created_at,
        };

        // Add to local state
        setOffers((prev) => [offer, ...prev]);

        return { ok: true, offer };
      } catch (err) {
        if (err instanceof AuthError) {
          return { ok: false, error: 'Invalid API key – check environment variables.' };
        }
        return {
          ok: false,
          error: err instanceof Error ? err.message : 'Failed to create offer',
        };
      }
    },
    []
  );

  useEffect(() => {
    fetchOffers();
  }, [fetchOffers]);

  return {
    offers,
    loading,
    error,
    isAuthError,
    isNotFound,
    createOffer,
    refetch: fetchOffers,
  };
}
