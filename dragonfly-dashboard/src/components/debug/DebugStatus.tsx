/**
 * DebugStatus - Temporary debug component for Vercel env var verification
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Displays the VITE_API_BASE_URL on screen for debugging.
 * Always visible - remove this component after debugging is complete.
 *
 * Add to App.tsx or a layout component:
 *   import { DebugStatus } from '@/components/debug/DebugStatus';
 *   // In your JSX:
 *   <DebugStatus />
 */

export function DebugStatus() {
  const baseUrl = import.meta.env.VITE_API_BASE_URL ?? '(undefined)';

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
      Target: {baseUrl}
    </div>
  );
}

export default DebugStatus;
