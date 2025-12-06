/**
 * useIntelligence
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Hook for fetching intelligence graph data via apiClient.
 * Returns entities and relationships for a given judgment.
 */
import { useCallback, useEffect, useState } from 'react';
import { apiClient, AuthError, NotFoundError } from '../lib/apiClient';
import { IS_DEMO_MODE } from '../lib/supabaseClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface IntelligenceEntity {
  id: string;
  type: 'person' | 'company' | 'court' | 'address' | 'other';
  rawName: string;
  normalizedName: string;
  metadata: Record<string, unknown>;
}

export interface IntelligenceRelationship {
  id: string;
  sourceEntityId: string;
  targetEntityId: string;
  relation: 'plaintiff_in' | 'defendant_in' | 'filed_at' | 'located_at' | 'related_to';
  confidence: number;
  sourceJudgmentId: number | null;
}

export interface IntelligenceData {
  judgmentId: number;
  entities: IntelligenceEntity[];
  relationships: IntelligenceRelationship[];
}

export interface IntelligenceResult {
  data: IntelligenceData | null;
  loading: boolean;
  error: string | null;
  isAuthError: boolean;
  isNotFound: boolean;
  refetch: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// API RESPONSE
// ═══════════════════════════════════════════════════════════════════════════

interface ApiIntelligenceResponse {
  judgment_id: number;
  entities: Array<{
    id: string;
    type: string;
    raw_name: string;
    normalized_name: string;
    metadata?: Record<string, unknown>;
  }>;
  relationships: Array<{
    id: string;
    source_entity_id: string;
    target_entity_id: string;
    relation: string;
    confidence: number;
    source_judgment_id: number | null;
  }>;
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useIntelligence(judgmentId: number | null): IntelligenceResult {
  const [data, setData] = useState<IntelligenceData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthError, setIsAuthError] = useState(false);
  const [isNotFound, setIsNotFound] = useState(false);

  const fetchData = useCallback(async () => {
    if (!judgmentId) {
      setData(null);
      setError(null);
      setIsAuthError(false);
      setIsNotFound(false);
      return;
    }

    if (IS_DEMO_MODE) {
      // Return mock data for demo mode
      setData({
        judgmentId,
        entities: [
          {
            id: 'demo-entity-1',
            type: 'person',
            rawName: 'John Doe',
            normalizedName: 'john doe',
            metadata: {},
          },
          {
            id: 'demo-entity-2',
            type: 'company',
            rawName: 'ABC Corporation',
            normalizedName: 'abc corporation',
            metadata: {},
          },
          {
            id: 'demo-entity-3',
            type: 'court',
            rawName: 'New York Supreme Court',
            normalizedName: 'new york supreme court',
            metadata: { county: 'New York' },
          },
        ],
        relationships: [
          {
            id: 'demo-rel-1',
            sourceEntityId: 'demo-entity-1',
            targetEntityId: 'demo-entity-3',
            relation: 'plaintiff_in',
            confidence: 1.0,
            sourceJudgmentId: judgmentId,
          },
          {
            id: 'demo-rel-2',
            sourceEntityId: 'demo-entity-2',
            targetEntityId: 'demo-entity-3',
            relation: 'defendant_in',
            confidence: 1.0,
            sourceJudgmentId: judgmentId,
          },
        ],
      });
      setLoading(false);
      setIsAuthError(false);
      setIsNotFound(false);
      return;
    }

    setLoading(true);
    setError(null);
    setIsAuthError(false);
    setIsNotFound(false);

    try {
      const json = await apiClient.get<ApiIntelligenceResponse>(
        `/api/v1/intelligence/judgment/${judgmentId}`
      );

      // Transform snake_case to camelCase
      setData({
        judgmentId: json.judgment_id,
        entities: (json.entities || []).map((e) => ({
          id: e.id,
          type: e.type as IntelligenceEntity['type'],
          rawName: e.raw_name,
          normalizedName: e.normalized_name,
          metadata: e.metadata || {},
        })),
        relationships: (json.relationships || []).map((r) => ({
          id: r.id,
          sourceEntityId: r.source_entity_id,
          targetEntityId: r.target_entity_id,
          relation: r.relation as IntelligenceRelationship['relation'],
          confidence: r.confidence,
          sourceJudgmentId: r.source_judgment_id,
        })),
      });
    } catch (err) {
      if (err instanceof AuthError) {
        setError('Authentication failed – check your API key');
        setIsAuthError(true);
      } else if (err instanceof NotFoundError) {
        setError('No intelligence data found for this judgment');
        setIsNotFound(true);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to fetch intelligence data');
      }
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [judgmentId]);

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
