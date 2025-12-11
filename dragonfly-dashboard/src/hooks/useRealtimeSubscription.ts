/**
 * useRealtimeSubscription - Supabase Realtime Database Subscriptions
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Provides real-time database change notifications via Supabase Realtime.
 * Automatically reconnects on connection loss and handles cleanup.
 *
 * Features:
 *   - Subscribe to INSERT, UPDATE, DELETE events on any table
 *   - Schema-aware (supports ops, enforcement, public, analytics)
 *   - Automatic reconnection with exponential backoff
 *   - Flash callback for UI animations
 *   - Demo mode safe (disabled when IS_DEMO_MODE)
 *
 * Usage:
 *   const { isConnected } = useRealtimeSubscription({
 *     table: 'job_queue',
 *     schema: 'ops',
 *     event: '*',
 *     onInsert: (payload) => refetch(),
 *     onFlash: () => setFlash(true),
 *   });
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { getSupabaseClient, IS_DEMO_MODE } from '../lib/supabaseClient';
import type { RealtimeChannel } from '@supabase/supabase-js';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type RealtimeEvent = 'INSERT' | 'UPDATE' | 'DELETE' | '*';

export interface RealtimePayload<T = Record<string, unknown>> {
  eventType: RealtimeEvent;
  new: T | null;
  old: T | null;
  table: string;
  schema: string;
  commitTimestamp: string;
}

export interface UseRealtimeSubscriptionOptions<T = Record<string, unknown>> {
  /** Table name to subscribe to */
  table: string;
  /** Schema name (default: 'public') */
  schema?: string;
  /** Event type to listen for (default: '*' for all) */
  event?: RealtimeEvent;
  /** Filter expression (e.g., 'status=eq.completed') */
  filter?: string;
  /** Callback when INSERT occurs */
  onInsert?: (payload: RealtimePayload<T>) => void;
  /** Callback when UPDATE occurs */
  onUpdate?: (payload: RealtimePayload<T>) => void;
  /** Callback when DELETE occurs */
  onDelete?: (payload: RealtimePayload<T>) => void;
  /** Callback for any change (runs before specific callbacks) */
  onChange?: (payload: RealtimePayload<T>) => void;
  /** Callback to trigger UI flash animation */
  onFlash?: () => void;
  /** Whether subscription is enabled (default: true) */
  enabled?: boolean;
}

export interface UseRealtimeSubscriptionResult {
  /** Whether connected to realtime channel */
  isConnected: boolean;
  /** Connection error if any */
  error: string | null;
  /** Number of events received */
  eventCount: number;
  /** Last event timestamp */
  lastEventAt: Date | null;
  /** Manually reconnect */
  reconnect: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useRealtimeSubscription<T = Record<string, unknown>>(
  options: UseRealtimeSubscriptionOptions<T>
): UseRealtimeSubscriptionResult {
  const {
    table,
    schema = 'public',
    event = '*',
    filter,
    onInsert,
    onUpdate,
    onDelete,
    onChange,
    onFlash,
    enabled = true,
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [eventCount, setEventCount] = useState(0);
  const [lastEventAt, setLastEventAt] = useState<Date | null>(null);

  const channelRef = useRef<RealtimeChannel | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempts = useRef(0);

  const cleanup = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (channelRef.current) {
      const client = getSupabaseClient();
      client.removeChannel(channelRef.current);
      channelRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const connect = useCallback(() => {
    // Don't connect in demo mode
    if (IS_DEMO_MODE) {
      console.log('[Realtime] Demo mode - subscriptions disabled');
      return;
    }

    if (!enabled) {
      return;
    }

    cleanup();

    const client = getSupabaseClient();
    const channelName = `realtime:${schema}:${table}:${Date.now()}`;

    try {
      // Create the channel
      const channel = client.channel(channelName);

      // Subscribe to postgres changes using the proper v2 API
      // We use 'as unknown as' to work around strict typing with postgres_changes
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (channel as any).on(
        'postgres_changes',
        {
          event: event,
          schema: schema,
          table: table,
          ...(filter ? { filter } : {}),
        },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (payload: any) => {
          const eventPayload: RealtimePayload<T> = {
            eventType: payload.eventType as RealtimeEvent,
            new: payload.new as T | null,
            old: payload.old as T | null,
            table: payload.table ?? table,
            schema: payload.schema ?? schema,
            commitTimestamp: payload.commit_timestamp ?? new Date().toISOString(),
          };

          // Update stats
          setEventCount((prev) => prev + 1);
          setLastEventAt(new Date());

          // Trigger flash animation
          if (onFlash) {
            onFlash();
          }

          // Call generic onChange first
          if (onChange) {
            onChange(eventPayload);
          }

          // Call specific event handlers
          switch (payload.eventType) {
            case 'INSERT':
              if (onInsert) onInsert(eventPayload);
              break;
            case 'UPDATE':
              if (onUpdate) onUpdate(eventPayload);
              break;
            case 'DELETE':
              if (onDelete) onDelete(eventPayload);
              break;
          }
        }
      );

      // Subscribe and handle status
      channel.subscribe((status) => {
        if (status === 'SUBSCRIBED') {
          setIsConnected(true);
          setError(null);
          reconnectAttempts.current = 0;
          console.log(`[Realtime] Connected to ${schema}.${table}`);
        } else if (status === 'CLOSED' || status === 'CHANNEL_ERROR') {
          setIsConnected(false);
          setError(`Channel ${status.toLowerCase()}`);

          // Exponential backoff reconnection
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
          reconnectAttempts.current += 1;

          console.log(`[Realtime] Reconnecting in ${delay}ms (attempt ${reconnectAttempts.current})`);
          reconnectTimeoutRef.current = setTimeout(connect, delay);
        }
      });

      channelRef.current = channel;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to create channel';
      setError(message);
      console.error('[Realtime] Connection error:', message);
    }
  }, [table, schema, event, filter, enabled, onInsert, onUpdate, onDelete, onChange, onFlash, cleanup]);

  // Initial connection
  useEffect(() => {
    connect();
    return cleanup;
  }, [connect, cleanup]);

  const reconnect = useCallback(() => {
    reconnectAttempts.current = 0;
    connect();
  }, [connect]);

  return {
    isConnected,
    error,
    eventCount,
    lastEventAt,
    reconnect,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// CONVENIENCE HOOKS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Subscribe to job queue changes (ops.job_queue)
 */
export function useJobQueueRealtime(options: {
  onJobComplete?: (jobId: string, status: string) => void;
  onFlash?: () => void;
  enabled?: boolean;
}) {
  const { onJobComplete, onFlash, enabled = true } = options;

  return useRealtimeSubscription({
    table: 'job_queue',
    schema: 'ops',
    event: 'UPDATE',
    onUpdate: (payload) => {
      const job = payload.new as { id?: string; status?: string } | null;
      if (job && onJobComplete) {
        onJobComplete(job.id ?? '', job.status ?? '');
      }
    },
    onFlash,
    enabled,
  });
}

/**
 * Subscribe to draft packet changes (enforcement.draft_packets)
 */
export function usePacketRealtime(options: {
  onPacketCreated?: (packetId: string, strategy: string) => void;
  onFlash?: () => void;
  enabled?: boolean;
}) {
  const { onPacketCreated, onFlash, enabled = true } = options;

  return useRealtimeSubscription({
    table: 'draft_packets',
    schema: 'enforcement',
    event: 'INSERT',
    onInsert: (payload) => {
      const packet = payload.new as { id?: string; strategy?: string } | null;
      if (packet && onPacketCreated) {
        onPacketCreated(packet.id ?? '', packet.strategy ?? 'enforcement');
      }
    },
    onFlash,
    enabled,
  });
}

/**
 * Subscribe to new judgment insertions (public.judgments)
 */
export function useJudgmentRealtime(options: {
  onJudgmentIngested?: (judgmentId: string, amount: number) => void;
  onFlash?: () => void;
  enabled?: boolean;
}) {
  const { onJudgmentIngested, onFlash, enabled = true } = options;

  return useRealtimeSubscription({
    table: 'judgments',
    schema: 'public',
    event: 'INSERT',
    onInsert: (payload) => {
      const judgment = payload.new as { id?: string; principal_amount?: number } | null;
      if (judgment && onJudgmentIngested) {
        onJudgmentIngested(judgment.id ?? '', judgment.principal_amount ?? 0);
      }
    },
    onFlash,
    enabled,
  });
}

export default useRealtimeSubscription;
