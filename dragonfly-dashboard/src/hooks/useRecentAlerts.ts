/**
 * useRecentAlerts
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Fetches recent system alerts and notifications for the Portfolio Dashboard.
 * Includes spend guard blocks, daily recaps, enrichment completions, etc.
 */
import { useCallback, useEffect, useState } from 'react';
import { IS_DEMO_MODE } from '../lib/supabaseClient';
import { useOnRefresh } from '../context/RefreshContext';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type AlertSeverity = 'info' | 'warning' | 'success' | 'error';
export type AlertCategory = 'spend_guard' | 'daily_recap' | 'enrichment' | 'service' | 'collection' | 'system';

export interface SystemAlert {
  id: string;
  category: AlertCategory;
  severity: AlertSeverity;
  title: string;
  message: string;
  caseNumber?: string;
  timestamp: string;
  read: boolean;
}

export interface RecentAlertsResult {
  alerts: SystemAlert[];
  loading: boolean;
  error: string | null;
  unreadCount: number;
  markAsRead: (id: string) => void;
  refetch: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// DEMO DATA
// ═══════════════════════════════════════════════════════════════════════════

const DEMO_ALERTS: SystemAlert[] = [
  {
    id: 'alert-1',
    category: 'spend_guard',
    severity: 'warning',
    title: 'Spend Guard: Service Blocked',
    message: 'Case #2024-CV-4892 exceeded $500 service budget. Awaiting approval.',
    caseNumber: '2024-CV-4892',
    timestamp: new Date(Date.now() - 1000 * 60 * 15).toISOString(), // 15 min ago
    read: false,
  },
  {
    id: 'alert-2',
    category: 'daily_recap',
    severity: 'info',
    title: 'Daily Recap Email Sent',
    message: '12 new judgments processed, $842K added to pipeline.',
    timestamp: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(), // 2 hours ago
    read: false,
  },
  {
    id: 'alert-3',
    category: 'enrichment',
    severity: 'success',
    title: 'Batch Enrichment Complete',
    message: '45 cases enriched. 8 flagged as gig economy candidates.',
    timestamp: new Date(Date.now() - 1000 * 60 * 60 * 4).toISOString(), // 4 hours ago
    read: true,
  },
  {
    id: 'alert-4',
    category: 'service',
    severity: 'success',
    title: 'Service Confirmed',
    message: 'Johnson v. Smith (2024-CV-3421) successfully served.',
    caseNumber: '2024-CV-3421',
    timestamp: new Date(Date.now() - 1000 * 60 * 60 * 6).toISOString(), // 6 hours ago
    read: true,
  },
  {
    id: 'alert-5',
    category: 'collection',
    severity: 'success',
    title: 'Payment Received',
    message: '$12,450 collected on case #2024-CV-2156.',
    caseNumber: '2024-CV-2156',
    timestamp: new Date(Date.now() - 1000 * 60 * 60 * 8).toISOString(), // 8 hours ago
    read: true,
  },
  {
    id: 'alert-6',
    category: 'spend_guard',
    severity: 'error',
    title: 'Budget Exhausted',
    message: 'Monthly service budget 95% utilized. Review pending cases.',
    timestamp: new Date(Date.now() - 1000 * 60 * 60 * 24).toISOString(), // 1 day ago
    read: true,
  },
];

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useRecentAlerts(limit: number = 10): RecentAlertsResult {
  const [alerts, setAlerts] = useState<SystemAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAlerts = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      if (IS_DEMO_MODE) {
        // Demo mode: return mock alerts
        await new Promise((r) => setTimeout(r, 300)); // Simulate network
        setAlerts(DEMO_ALERTS.slice(0, limit));
      } else {
        // TODO: Implement real API call when endpoint is available
        // For now, use demo data in all modes
        setAlerts(DEMO_ALERTS.slice(0, limit));
      }
    } catch (err) {
      console.error('[useRecentAlerts]', err);
      setError(err instanceof Error ? err.message : 'Failed to load alerts');
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  useOnRefresh(fetchAlerts);

  const markAsRead = useCallback((id: string) => {
    setAlerts((prev) =>
      prev.map((alert) => (alert.id === id ? { ...alert, read: true } : alert))
    );
  }, []);

  const unreadCount = alerts.filter((a) => !a.read).length;

  return { alerts, loading, error, unreadCount, markAsRead, refetch: fetchAlerts };
}

export default useRecentAlerts;
