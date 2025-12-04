/**
 * useOffers
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Hook for creating offers and fetching offer history for a judgment.
 */
import { useCallback, useEffect, useState } from 'react';
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
  createOffer: (payload: CreateOfferPayload) => Promise<CreateOfferResult>;
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

export function useOffers(judgmentId: number | null): OffersResult {
  const [offers, setOffers] = useState<Offer[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchOffers = useCallback(async () => {
    if (!judgmentId) {
      setOffers([]);
      setError(null);
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

    try {
      const baseUrl = getApiBaseUrl();
      const response = await fetch(`${baseUrl}/api/v1/offers?judgment_id=${judgmentId}`);

      if (!response.ok) {
        // If 404, that's fine - no offers yet
        if (response.status === 404) {
          setOffers([]);
          return;
        }
        const errorData = await response.json().catch(() => ({}));
        setError(errorData.detail || `API error: ${response.status}`);
        setOffers([]);
        return;
      }

      const json = await response.json();
      const offersList = Array.isArray(json) ? json : json.offers || [];

      setOffers(
        offersList.map((o: Record<string, unknown>) => ({
          id: o.id as string,
          judgmentId: o.judgment_id as number,
          offerAmount: o.offer_amount as number,
          offerType: o.offer_type as 'purchase' | 'contingency',
          status: o.status as Offer['status'],
          operatorNotes: (o.operator_notes as string) || '',
          createdAt: o.created_at as string,
        }))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch offers');
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
        const baseUrl = getApiBaseUrl();
        const response = await fetch(`${baseUrl}/api/v1/offers`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          return { ok: false, error: errorData.detail || `API error: ${response.status}` };
        }

        const json = await response.json();
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
    createOffer,
    refetch: fetchOffers,
  };
}
