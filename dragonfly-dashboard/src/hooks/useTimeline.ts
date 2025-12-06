/**
 * useTimeline Hook
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Custom hooks for fetching entity and judgment timelines from the
 * Intelligence API. Uses unified apiClient for all API calls.
 */
import { useState, useEffect, useCallback } from 'react';
import { apiClient, AuthError, NotFoundError } from '../lib/apiClient';

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
  isAuthError: boolean;
  isNotFound: boolean;
  refetch: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOKS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Fetch timeline events for an entity by entity ID.
 */
export function useEntityTimeline(
  entityId: string | undefined,
  limit: number = 100
): UseTimelineResult {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthError, setIsAuthError] = useState(false);
  const [isNotFound, setIsNotFound] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const refetch = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    if (!entityId) {
      setEvents([]);
      setIsLoading(false);
      setError(null);
      setIsAuthError(false);
      setIsNotFound(false);
      return;
    }

    let cancelled = false;

    const fetchTimeline = async () => {
      setIsLoading(true);
      setError(null);
      setIsAuthError(false);
      setIsNotFound(false);

      try {
        const data = await apiClient.get<TimelineResponse>(
          `/api/v1/intelligence/entity/${entityId}/timeline?limit=${limit}`
        );
        if (!cancelled) {
          setEvents(data.events);
        }
      } catch (err) {
        console.error('Entity timeline fetch error:', err);
        if (!cancelled) {
          if (err instanceof AuthError) {
            setIsAuthError(true);
            setError('Invalid API key – check environment variables.');
          } else if (err instanceof NotFoundError) {
            setIsNotFound(true);
            setEvents([]);
          } else {
            setError(err instanceof Error ? err.message : 'Failed to load timeline');
          }
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

  return { events, isLoading, error, isAuthError, isNotFound, refetch };
}

/**
 * Fetch timeline events for a judgment by judgment ID.
 */
export function useJudgmentTimeline(
  judgmentId: number | undefined,
  limit: number = 100
): UseTimelineResult {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthError, setIsAuthError] = useState(false);
  const [isNotFound, setIsNotFound] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const refetch = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    if (!judgmentId) {
      setEvents([]);
      setIsLoading(false);
      setError(null);
      setIsAuthError(false);
      setIsNotFound(false);
      return;
    }

    let cancelled = false;

    const fetchTimeline = async () => {
      setIsLoading(true);
      setError(null);
      setIsAuthError(false);
      setIsNotFound(false);

      try {
        const data = await apiClient.get<TimelineResponse>(
          `/api/v1/intelligence/judgment/${judgmentId}/timeline?limit=${limit}`
        );
        if (!cancelled) {
          setEvents(data.events);
        }
      } catch (err) {
        console.error('Judgment timeline fetch error:', err);
        if (!cancelled) {
          if (err instanceof AuthError) {
            setIsAuthError(true);
            setError('Invalid API key – check environment variables.');
          } else if (err instanceof NotFoundError) {
            setIsNotFound(true);
            setEvents([]);
          } else {
            setError(err instanceof Error ? err.message : 'Failed to load timeline');
          }
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

  return { events, isLoading, error, isAuthError, isNotFound, refetch };
}

/**
 * Unified hook that picks the right timeline based on provided IDs.
 * Prefers entityId over judgmentId if both are provided.
 */
export function useTimeline(
  entityId?: string,
  judgmentId?: number,
  limit: number = 100
): UseTimelineResult {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAuthError, setIsAuthError] = useState(false);
  const [isNotFound, setIsNotFound] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const refetch = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    if (!entityId && !judgmentId) {
      setEvents([]);
      setIsLoading(false);
      setError(null);
      setIsAuthError(false);
      setIsNotFound(false);
      return;
    }

    let cancelled = false;

    const fetchTimeline = async () => {
      setIsLoading(true);
      setError(null);
      setIsAuthError(false);
      setIsNotFound(false);

      try {
        const url = entityId
          ? `/api/v1/intelligence/entity/${entityId}/timeline?limit=${limit}`
          : `/api/v1/intelligence/judgment/${judgmentId}/timeline?limit=${limit}`;

        const data = await apiClient.get<TimelineResponse>(url);
        if (!cancelled) {
          setEvents(data.events);
        }
      } catch (err) {
        console.error('Timeline fetch error:', err);
        if (!cancelled) {
          if (err instanceof AuthError) {
            setIsAuthError(true);
            setError('Invalid API key – check environment variables.');
          } else if (err instanceof NotFoundError) {
            setIsNotFound(true);
            setEvents([]);
          } else {
            setError(err instanceof Error ? err.message : 'Failed to load timeline');
          }
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

  return { events, isLoading, error, isAuthError, isNotFound, refetch };
}
