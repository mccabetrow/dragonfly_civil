/**
 * DebugStatus - Temporary debug component for Vercel env var verification
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Displays the API base URL on screen for debugging.
 * Only visible in development mode.
 *
 * Add to App.tsx or a layout component:
 *   import { DebugStatus } from '@/components/debug/DebugStatus';
 *   // In your JSX:
 *   <DebugStatus />
 */

import { apiBaseUrl, isDev } from '../../config';

export function DebugStatus() {
  // Only show in development
  if (!isDev) return null;

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 0,
        right: 0,
        background: 'red',
        color: 'white',
        zIndex: 9999,
        padding: '4px',
        fontSize: '10px',
      }}
    >
      Target: {apiBaseUrl || '(undefined)'}
    </div>
  );
}

export default DebugStatus;
