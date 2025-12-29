/**
 * RealtimeStatusBanner - User-facing banner for realtime connection issues
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Shows a dismissable banner when realtime connection fails, especially for
 * authentication errors. Designed to inform without alarming.
 *
 * Behavior:
 *   - Only shows when isAuthError is true (auth-specific failures)
 *   - Dismissable via X button
 *   - Includes Retry button
 *   - Non-blocking - app continues to function via polling
 */
import React from 'react';
import { useRealtimeStatus } from '../context/RealtimeContext';

export const RealtimeStatusBanner: React.FC = () => {
  const { status, isAuthError, error, reconnect, dismissAuthError } = useRealtimeStatus();

  // Only show banner for auth errors (not transient disconnects)
  if (!isAuthError) {
    return null;
  }

  return (
    <div className="fixed bottom-4 left-1/2 transform -translate-x-1/2 z-50 max-w-xl w-full px-4">
      <div className="bg-amber-900/95 border border-amber-600 rounded-lg shadow-lg p-4">
        <div className="flex items-start gap-3">
          {/* Warning Icon */}
          <div className="flex-shrink-0 mt-0.5">
            <svg className="h-5 w-5 text-amber-400" viewBox="0 0 20 20" fill="currentColor">
              <path
                fillRule="evenodd"
                d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z"
                clipRule="evenodd"
              />
            </svg>
          </div>

          {/* Message */}
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-medium text-amber-200">
              Realtime Disconnected (auth failed)
            </h3>
            <p className="mt-1 text-xs text-amber-300/80">
              Live updates paused. The app will continue working via polling.
              {error && (
                <span className="block mt-1 font-mono text-[10px] text-amber-400/60 truncate">
                  {error}
                </span>
              )}
            </p>
          </div>

          {/* Actions */}
          <div className="flex-shrink-0 flex items-center gap-2">
            {/* Retry Button */}
            <button
              onClick={reconnect}
              disabled={status === 'connecting'}
              className="px-2.5 py-1 text-xs font-medium text-amber-900 bg-amber-400 hover:bg-amber-300 rounded transition-colors disabled:opacity-50"
            >
              {status === 'connecting' ? 'Retrying...' : 'Retry'}
            </button>

            {/* Dismiss Button */}
            <button
              onClick={dismissAuthError}
              className="p-1 text-amber-400 hover:text-amber-200 transition-colors"
              aria-label="Dismiss"
            >
              <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default RealtimeStatusBanner;
