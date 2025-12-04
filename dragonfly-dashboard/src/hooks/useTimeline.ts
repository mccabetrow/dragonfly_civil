/**
 * useTimeline Hook
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Custom hooks for fetching entity and judgment timelines from the
 * Intelligence API.
 */
import { useState, useEffect, useCallback } from 'react';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface TimelineEvent {
  id: string;
  event_type: string;
  created_at: string;
  payload: Record<string, unknown>;
  summary: string;
}

interface TimelineResponse {
  events: TimelineEvent[];
  total: number;
}

interface UseTimelineResult {
  events: TimelineEvent[];
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOKS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Fetch timeline events for an entity by entity ID.
 *
 * @param entityId - UUID of the entity
 * @param limit - Maximum number of events to return (default: 100)
 * @returns Timeline events, loading state, and error
 */
export function useEntityTimeline(
  entityId: string | undefined,
  limit: number = 100
): UseTimelineResult {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const refetch = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    if (!entityId) {
      setEvents([]);
      setIsLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;

    const fetchTimeline = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const url = `/api/v1/intelligence/entity/${entityId}/timeline?limit=${limit}`;
        const response = await fetch(url);

        if (!response.ok) {
          throw new Error(`Failed to fetch timeline: ${response.statusText}`);
        }

        const data: TimelineResponse = await response.json();

        if (!cancelled) {
          setEvents(data.events);
        }
      } catch (err) {
        console.error('Entity timeline fetch error:', err);
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load timeline');
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    fetchTimeline();

    return () => {
      cancelled = true;
    };
  }, [entityId, limit, refreshKey]);

  return { events, isLoading, error, refetch };
}

/**
 * Fetch timeline events for a judgment by judgment ID.
 * This endpoint looks up the defendant entity for the judgment first.
 *
 * @param judgmentId - Numeric ID of the judgment
 * @param limit - Maximum number of events to return (default: 100)
 * @returns Timeline events, loading state, and error
 */
export function useJudgmentTimeline(
  judgmentId: number | undefined,
  limit: number = 100
): UseTimelineResult {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const refetch = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    if (!judgmentId) {
      setEvents([]);
      setIsLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;

    const fetchTimeline = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const url = `/api/v1/intelligence/judgment/${judgmentId}/timeline?limit=${limit}`;
        const response = await fetch(url);

        if (!response.ok) {
          throw new Error(`Failed to fetch timeline: ${response.statusText}`);
        }

        const data: TimelineResponse = await response.json();

        if (!cancelled) {
          setEvents(data.events);
        }
      } catch (err) {
        console.error('Judgment timeline fetch error:', err);
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load timeline');
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    fetchTimeline();

    return () => {
      cancelled = true;
    };
  }, [judgmentId, limit, refreshKey]);

  return { events, isLoading, error, refetch };
}

/**
 * Unified hook that picks the right timeline based on provided IDs.
 * Prefers entityId over judgmentId if both are provided.
 *
 * @param entityId - UUID of the entity (takes precedence)
 * @param judgmentId - Numeric ID of the judgment
 * @param limit - Maximum number of events to return (default: 100)
 * @returns Timeline events, loading state, and error
 */
export function useTimeline(
  entityId?: string,
  judgmentId?: number,
  limit: number = 100
): UseTimelineResult {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const refetch = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    // No IDs provided
    if (!entityId && !judgmentId) {
      setEvents([]);
      setIsLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;

    const fetchTimeline = async () => {
      setIsLoading(true);
      setError(null);

      try {
        // Prefer entityId over judgmentId
        const url = entityId
          ? `/api/v1/intelligence/entity/${entityId}/timeline?limit=${limit}`
          : `/api/v1/intelligence/judgment/${judgmentId}/timeline?limit=${limit}`;

        const response = await fetch(url);

        if (!response.ok) {
          throw new Error(`Failed to fetch timeline: ${response.statusText}`);
        }

        const data: TimelineResponse = await response.json();

        if (!cancelled) {
          setEvents(data.events);
        }
      } catch (err) {
        console.error('Timeline fetch error:', err);
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load timeline');
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    fetchTimeline();

    return () => {
      cancelled = true;
    };
  }, [entityId, judgmentId, limit, refreshKey]);

  return { events, isLoading, error, refetch };
}
