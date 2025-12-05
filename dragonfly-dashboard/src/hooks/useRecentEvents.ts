/**
 * useRecentEvents
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Fetches recent intelligence.events for the CEO Overview activity feed.
 * Returns events with friendly labels for display.
 */
import { useCallback, useEffect, useState } from 'react';
import { IS_DEMO_MODE, supabaseClient } from '../lib/supabaseClient';
import { useOnRefresh } from '../context/RefreshContext';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type EventType =
  | 'judgment_created'
  | 'judgment_enriched'
  | 'offer_created'
  | 'offer_accepted'
  | 'offer_rejected'
  | 'batch_ingested'
  | 'entity_linked'
  | 'score_updated'
  | 'packet_generated'
  | 'system_alert'
  | 'unknown';

export interface RecentEvent {
  id: string;
  eventType: EventType;
  label: string;
  description: string;
  timestamp: string;
  metadata: Record<string, unknown>;
  judgmentId: number | null;
  entityId: string | null;
}

export interface RecentEventsResult {
  data: RecentEvent[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// EVENT LABELS
// ═══════════════════════════════════════════════════════════════════════════

const EVENT_LABELS: Record<EventType, string> = {
  judgment_created: 'New Judgment Added',
  judgment_enriched: 'Judgment Enriched',
  offer_created: 'Offer Submitted',
  offer_accepted: 'Offer Accepted',
  offer_rejected: 'Offer Rejected',
  batch_ingested: 'Batch Ingested',
  entity_linked: 'Entity Linked',
  score_updated: 'Score Updated',
  packet_generated: 'Packet Generated',
  system_alert: 'System Alert',
  unknown: 'Event',
};

const EVENT_DESCRIPTIONS: Record<EventType, (meta: Record<string, unknown>) => string> = {
  judgment_created: (meta) =>
    `Case ${meta.case_number ?? 'N/A'} added to portfolio`,
  judgment_enriched: (meta) =>
    `Enrichment completed for case ${meta.case_number ?? 'N/A'}`,
  offer_created: (meta) =>
    `Offer of $${(Number(meta.amount) || 0).toLocaleString()} submitted`,
  offer_accepted: (meta) =>
    `Offer accepted for $${(Number(meta.amount) || 0).toLocaleString()}`,
  offer_rejected: (meta) =>
    meta.reason ? `Offer rejected: ${meta.reason}` : 'Offer rejected',
  batch_ingested: (meta) =>
    `${meta.row_count ?? 'N/A'} records ingested from ${meta.source ?? 'batch'}`,
  entity_linked: (meta) =>
    `Entity "${meta.entity_name ?? 'unknown'}" linked to case`,
  score_updated: (meta) =>
    `Score updated to ${meta.new_score ?? 'N/A'}/100`,
  packet_generated: (meta) =>
    `Legal packet generated for case ${meta.case_number ?? 'N/A'}`,
  system_alert: (meta) =>
    meta.message ? String(meta.message) : 'System notification',
  unknown: () => 'System event occurred',
};

// ═══════════════════════════════════════════════════════════════════════════
// DEMO DATA
// ═══════════════════════════════════════════════════════════════════════════

const generateDemoEvents = (): RecentEvent[] => {
  const now = new Date();
  return [
    {
      id: 'demo-1',
      eventType: 'offer_accepted',
      label: 'Offer Accepted',
      description: 'Offer accepted for $45,000',
      timestamp: new Date(now.getTime() - 1000 * 60 * 15).toISOString(),
      metadata: { amount: 45000 },
      judgmentId: 123,
      entityId: null,
    },
    {
      id: 'demo-2',
      eventType: 'batch_ingested',
      label: 'Batch Ingested',
      description: '127 records ingested from Simplicity',
      timestamp: new Date(now.getTime() - 1000 * 60 * 45).toISOString(),
      metadata: { row_count: 127, source: 'Simplicity' },
      judgmentId: null,
      entityId: null,
    },
    {
      id: 'demo-3',
      eventType: 'judgment_enriched',
      label: 'Judgment Enriched',
      description: 'Enrichment completed for case NY-2024-00456',
      timestamp: new Date(now.getTime() - 1000 * 60 * 90).toISOString(),
      metadata: { case_number: 'NY-2024-00456' },
      judgmentId: 456,
      entityId: null,
    },
    {
      id: 'demo-4',
      eventType: 'score_updated',
      label: 'Score Updated',
      description: 'Score updated to 85/100',
      timestamp: new Date(now.getTime() - 1000 * 60 * 120).toISOString(),
      metadata: { new_score: 85 },
      judgmentId: 789,
      entityId: null,
    },
    {
      id: 'demo-5',
      eventType: 'offer_created',
      label: 'Offer Submitted',
      description: 'Offer of $32,500 submitted',
      timestamp: new Date(now.getTime() - 1000 * 60 * 180).toISOString(),
      metadata: { amount: 32500 },
      judgmentId: 321,
      entityId: null,
    },
    {
      id: 'demo-6',
      eventType: 'packet_generated',
      label: 'Packet Generated',
      description: 'Legal packet generated for case NY-2024-00789',
      timestamp: new Date(now.getTime() - 1000 * 60 * 240).toISOString(),
      metadata: { case_number: 'NY-2024-00789' },
      judgmentId: 654,
      entityId: null,
    },
    {
      id: 'demo-7',
      eventType: 'judgment_created',
      label: 'New Judgment Added',
      description: 'Case NY-2024-00987 added to portfolio',
      timestamp: new Date(now.getTime() - 1000 * 60 * 300).toISOString(),
      metadata: { case_number: 'NY-2024-00987' },
      judgmentId: 987,
      entityId: null,
    },
  ];
};

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useRecentEvents(limit = 20): RecentEventsResult {
  const [data, setData] = useState<RecentEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setData(generateDemoEvents().slice(0, limit));
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const { data: rows, error: fetchError } = await supabaseClient
        .from('events')
        .select('id, event_type, metadata, created_at, judgment_id, entity_id')
        .order('created_at', { ascending: false })
        .limit(limit);

      if (fetchError) {
        throw fetchError;
      }

      const events: RecentEvent[] = (rows ?? []).map((row) => {
        const eventType = (row.event_type ?? 'unknown') as EventType;
        const metadata = (row.metadata ?? {}) as Record<string, unknown>;
        const label = EVENT_LABELS[eventType] ?? EVENT_LABELS.unknown;
        const descriptionFn = EVENT_DESCRIPTIONS[eventType] ?? EVENT_DESCRIPTIONS.unknown;

        return {
          id: String(row.id),
          eventType,
          label,
          description: descriptionFn(metadata),
          timestamp: row.created_at ?? new Date().toISOString(),
          metadata,
          judgmentId: row.judgment_id ?? null,
          entityId: row.entity_id ?? null,
        };
      });

      setData(events);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load recent events';
      console.error('useRecentEvents error:', err);
      setError(message);
      // Fall back to demo data on error
      setData(generateDemoEvents().slice(0, limit));
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Subscribe to global refresh
  useOnRefresh(fetchData);

  return { data, loading, error, refetch: fetchData };
}

export default useRecentEvents;
