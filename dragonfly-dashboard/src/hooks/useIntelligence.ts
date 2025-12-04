/**
 * useIntelligence
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Hook for fetching intelligence graph data via the backend API.
 * Returns entities and relationships for a given judgment.
 */
import { useCallback, useEffect, useState } from 'react';
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

export function useIntelligence(judgmentId: number | null): IntelligenceResult {
  const [data, setData] = useState<IntelligenceData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!judgmentId) {
      setData(null);
      setError(null);
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
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const baseUrl = getApiBaseUrl();
      const response = await fetch(`${baseUrl}/api/v1/intelligence/judgment/${judgmentId}`);

      if (!response.ok) {
        if (response.status === 404) {
          setError('No intelligence data found for this judgment');
        } else {
          const errorData = await response.json().catch(() => ({}));
          setError(errorData.detail || `API error: ${response.status}`);
        }
        setData(null);
        return;
      }

      const json = await response.json();

      // Transform snake_case to camelCase
      setData({
        judgmentId: json.judgment_id,
        entities: (json.entities || []).map((e: Record<string, unknown>) => ({
          id: e.id,
          type: e.type,
          rawName: e.raw_name,
          normalizedName: e.normalized_name,
          metadata: e.metadata || {},
        })),
        relationships: (json.relationships || []).map((r: Record<string, unknown>) => ({
          id: r.id,
          sourceEntityId: r.source_entity_id,
          targetEntityId: r.target_entity_id,
          relation: r.relation,
          confidence: r.confidence,
          sourceJudgmentId: r.source_judgment_id,
        })),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch intelligence data');
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
    refetch: fetchData,
  };
}
