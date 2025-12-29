/**
 * RealtimeContext - Global Supabase Realtime Connection State
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Provides global awareness of realtime connection status and auth errors.
 * Enables graceful degradation - app never crashes if realtime fails.
 *
 * Features:
 *   - Tracks connection state (connected, disconnected, auth_failed)
 *   - Exponential backoff reconnection (1s → 30s max)
 *   - Auth failure detection with user-facing banner
 *   - Graceful degradation - polling continues even if realtime fails
 */
import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { getSupabaseClient, IS_DEMO_MODE } from '../lib/supabaseClient';
import type { RealtimeChannel } from '@supabase/supabase-js';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type RealtimeStatus = 'connecting' | 'connected' | 'disconnected' | 'auth_failed' | 'disabled';

export interface RealtimeState {
  /** Current connection status */
  status: RealtimeStatus;
  /** Error message if any */
  error: string | null;
  /** Whether auth specifically failed (wrong key, etc.) */
  isAuthError: boolean;
  /** Number of reconnection attempts */
  reconnectAttempts: number;
  /** Manually trigger reconnection */
  reconnect: () => void;
  /** Dismiss the auth error banner */
  dismissAuthError: () => void;
}

const RealtimeContext = createContext<RealtimeState | null>(null);

// ═══════════════════════════════════════════════════════════════════════════
// AUTH ERROR DETECTION
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Detect if an error message indicates an authentication failure.
 * Common patterns from Supabase Realtime websocket errors.
 */
function isAuthFailure(error: string | null): boolean {
  if (!error) return false;
  const lower = error.toLowerCase();
  return (
    lower.includes('auth') ||
    lower.includes('unauthorized') ||
    lower.includes('401') ||
    lower.includes('forbidden') ||
    lower.includes('403') ||
    lower.includes('invalid api key') ||
    lower.includes('invalid token') ||
    lower.includes('jwt') ||
    lower.includes('anon key') ||
    lower.includes('apikey')
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// PROVIDER
// ═══════════════════════════════════════════════════════════════════════════

export const RealtimeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [status, setStatus] = useState<RealtimeStatus>('connecting');
  const [error, setError] = useState<string | null>(null);
  const [isAuthError, setIsAuthError] = useState(false);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const [authErrorDismissed, setAuthErrorDismissed] = useState(false);

  const channelRef = useRef<RealtimeChannel | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cleanup = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (channelRef.current) {
      try {
        const client = getSupabaseClient();
        client.removeChannel(channelRef.current);
      } catch {
        // Ignore cleanup errors
      }
      channelRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    // Demo mode - realtime disabled
    if (IS_DEMO_MODE) {
      setStatus('disabled');
      console.log('[Realtime] Demo mode - realtime disabled');
      return;
    }

    cleanup();
    setStatus('connecting');

    try {
      const client = getSupabaseClient();

      // Create a system heartbeat channel to monitor connection health
      const channel = client.channel('system:heartbeat', {
        config: {
          presence: { key: 'status' },
        },
      });

      channel
        .on('system', { event: '*' }, (payload) => {
          // Handle system-level events (auth errors surface here)
          console.log('[Realtime] System event:', payload);
          if (payload.message) {
            const msg = String(payload.message);
            if (isAuthFailure(msg)) {
              setStatus('auth_failed');
              setError(msg);
              setIsAuthError(true);
              console.error('[Realtime] Auth failure detected:', msg);
            }
          }
        })
        .subscribe((channelStatus, err) => {
          if (channelStatus === 'SUBSCRIBED') {
            setStatus('connected');
            setError(null);
            setIsAuthError(false);
            setReconnectAttempts(0);
            console.log('[Realtime] Connected (heartbeat channel)');
          } else if (channelStatus === 'CLOSED' || channelStatus === 'CHANNEL_ERROR') {
            const errorMsg = err?.message || `Channel ${channelStatus.toLowerCase()}`;
            console.warn('[Realtime] Channel status:', channelStatus, errorMsg);

            // Detect auth errors from the error object
            if (isAuthFailure(errorMsg) || (err && isAuthFailure(String(err)))) {
              setStatus('auth_failed');
              setError(errorMsg);
              setIsAuthError(true);
              console.error('[Realtime] Auth failure:', errorMsg);
              // Don't auto-reconnect on auth failures - it won't help
              return;
            }

            setStatus('disconnected');
            setError(errorMsg);

            // Exponential backoff reconnection
            const attempts = reconnectAttempts + 1;
            const delay = Math.min(1000 * Math.pow(2, attempts), 30000);
            setReconnectAttempts(attempts);

            console.log(`[Realtime] Reconnecting in ${delay}ms (attempt ${attempts})`);
            reconnectTimeoutRef.current = setTimeout(connect, delay);
          } else if (channelStatus === 'TIMED_OUT') {
            setStatus('disconnected');
            setError('Connection timed out');
            // Retry immediately on timeout
            reconnectTimeoutRef.current = setTimeout(connect, 2000);
          }
        });

      channelRef.current = channel;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to initialize realtime';
      console.error('[Realtime] Initialization error:', message);

      if (isAuthFailure(message)) {
        setStatus('auth_failed');
        setIsAuthError(true);
      } else {
        setStatus('disconnected');
      }
      setError(message);
    }
  }, [cleanup, reconnectAttempts]);

  // Initial connection on mount
  useEffect(() => {
    connect();
    return cleanup;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reconnect = useCallback(() => {
    setReconnectAttempts(0);
    setAuthErrorDismissed(false);
    connect();
  }, [connect]);

  const dismissAuthError = useCallback(() => {
    setAuthErrorDismissed(true);
  }, []);

  const value: RealtimeState = {
    status,
    error,
    isAuthError: isAuthError && !authErrorDismissed,
    reconnectAttempts,
    reconnect,
    dismissAuthError,
  };

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
};

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useRealtimeStatus(): RealtimeState {
  const context = useContext(RealtimeContext);
  if (!context) {
    // Return safe defaults if used outside provider (graceful degradation)
    return {
      status: 'disabled',
      error: null,
      isAuthError: false,
      reconnectAttempts: 0,
      reconnect: () => {},
      dismissAuthError: () => {},
    };
  }
  return context;
}

export default RealtimeContext;
