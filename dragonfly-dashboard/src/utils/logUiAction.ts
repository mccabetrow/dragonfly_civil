/**
 * UI Telemetry Logger
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Fire-and-forget utility for logging UI interactions to the backend.
 * Designed to be non-blocking - failures are logged but never throw.
 *
 * Usage:
 *   import { logUiAction } from '../utils/logUiAction';
 *
 *   logUiAction({
 *     eventName: 'intake.upload_submitted',
 *     context: { batchId: '123', rowCount: 50 },
 *   });
 */

import { apiClient } from '../lib/apiClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface LogUiActionParams {
  /** Event type identifier (e.g., 'intake.upload_submitted') */
  eventName: string;
  /** Event-specific metadata */
  context: Record<string, unknown>;
  /** Optional session identifier for event correlation */
  sessionId?: string;
}

interface UiActionResponse {
  status: string;
  event_id: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// SESSION MANAGEMENT
// ═══════════════════════════════════════════════════════════════════════════

const SESSION_STORAGE_KEY = 'dragonfly_session_id';

/**
 * Get or create a session ID for telemetry correlation.
 * Persists in sessionStorage for the duration of the browser session.
 */
function getOrCreateSessionId(): string {
  try {
    let sessionId = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (!sessionId) {
      sessionId = `sess_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;
      sessionStorage.setItem(SESSION_STORAGE_KEY, sessionId);
    }
    return sessionId;
  } catch {
    // sessionStorage not available (e.g., private browsing)
    return `sess_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// MAIN EXPORT
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Log a UI action to the telemetry endpoint.
 *
 * This is fire-and-forget - it will not throw or block.
 * Errors are logged to console but do not affect the calling code.
 *
 * @param params - Event name and context to log
 * @returns Promise that resolves when the request completes (or fails silently)
 */
export async function logUiAction(params: LogUiActionParams): Promise<void> {
  const { eventName, context, sessionId } = params;

  // Use provided sessionId or generate one
  const resolvedSessionId = sessionId ?? getOrCreateSessionId();

  try {
    await apiClient.post<UiActionResponse>('/api/v1/telemetry/ui-action', {
      event_name: eventName,
      context,
      session_id: resolvedSessionId,
    });

    // Log success in development only
    if (import.meta.env.DEV) {
      console.debug(`[Telemetry] Logged: ${eventName}`, context);
    }
  } catch (err) {
    // Fire-and-forget: log but don't throw
    console.warn('[Telemetry] Failed to log UI action:', eventName, err);
  }
}

/**
 * Pre-configured telemetry event loggers for common actions.
 * Use these for type-safe, consistent event naming.
 */
export const telemetry = {
  /**
   * Generic action logger for custom events.
   * Use when pre-configured methods don't fit.
   */
  logAction(params: {
    componentId: string;
    action: string;
    metadata?: Record<string, unknown>;
  }): void {
    logUiAction({
      eventName: `${params.componentId}.${params.action}`,
      context: params.metadata ?? {},
    });
  },

  /**
   * Log an intake upload submission.
   */
  intakeUploadSubmitted(context: {
    batchId?: string;
    filename?: string;
    rowCount?: number;
    validRows?: number;
    errorRows?: number;
    source?: string;
  }): void {
    logUiAction({
      eventName: 'intake.upload_submitted',
      context,
    });
  },

  /**
   * Log an enforcement packet generation click.
   */
  enforcementGeneratePacketClicked(context: {
    judgmentId: string;
    strategy?: string;
    collectabilityScore?: number;
    judgmentAmount?: number;
  }): void {
    logUiAction({
      eventName: 'enforcement.generate_packet_clicked',
      context,
    });
  },

  /**
   * Log a page view.
   */
  pageView(context: {
    path: string;
    title?: string;
    referrer?: string;
  }): void {
    logUiAction({
      eventName: 'navigation.page_view',
      context,
    });
  },

  /**
   * Log a filter change.
   */
  filterChanged(context: {
    page: string;
    filterName: string;
    filterValue: unknown;
  }): void {
    logUiAction({
      eventName: 'ui.filter_changed',
      context,
    });
  },

  /**
   * Log a data export action.
   */
  dataExported(context: {
    page: string;
    format: string;
    rowCount?: number;
  }): void {
    logUiAction({
      eventName: 'data.exported',
      context,
    });
  },

  /**
   * Log a status indicator click.
   */
  statusIndicatorClicked(context: {
    componentId: string;
    currentStatus: string;
  }): void {
    logUiAction({
      eventName: 'ui.status_indicator_clicked',
      context,
    });
  },
};

export default logUiAction;
