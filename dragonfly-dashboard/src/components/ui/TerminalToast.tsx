/**
 * TerminalToast - Financial Terminal Style Toast Component
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * A custom toast component styled like a financial terminal log entry:
 *   - Dark background (bg-slate-900)
 *   - Color-coded borders (emerald/amber/red)
 *   - Monospace font for message body
 *   - Timestamp on the left, message on the right
 *   - framer-motion slide-in/fade animations
 *
 * Usage:
 *   const toast = useTerminalToast();
 *   toast.log('Generating packet...', 'info');
 *   toast.success('Packet generated successfully');
 *   toast.error('Failed to generate packet');
 */
import {
  type FC,
  type ReactNode,
  createContext,
  useContext,
  useState,
  useCallback,
} from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Check, AlertTriangle, XCircle, Loader2, X, Info } from 'lucide-react';
import { cn } from '../../lib/design-tokens';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type TerminalToastVariant = 'success' | 'error' | 'warning' | 'info' | 'loading';

export interface TerminalToast {
  id: string;
  variant: TerminalToastVariant;
  message: string;
  timestamp: Date;
  duration?: number; // ms, 0 = no auto-dismiss
}

interface TerminalToastContextValue {
  toasts: TerminalToast[];
  addToast: (message: string, variant: TerminalToastVariant, duration?: number) => string;
  updateToast: (id: string, updates: Partial<Omit<TerminalToast, 'id'>>) => void;
  removeToast: (id: string) => void;
  clearToasts: () => void;
  // Convenience methods
  success: (message: string, duration?: number) => string;
  error: (message: string, duration?: number) => string;
  warning: (message: string, duration?: number) => string;
  info: (message: string, duration?: number) => string;
  loading: (message: string) => string;
}

// ═══════════════════════════════════════════════════════════════════════════
// CONTEXT
// ═══════════════════════════════════════════════════════════════════════════

const TerminalToastContext = createContext<TerminalToastContextValue | null>(null);

export const useTerminalToast = (): TerminalToastContextValue => {
  const context = useContext(TerminalToastContext);
  if (!context) {
    throw new Error('useTerminalToast must be used within a TerminalToastProvider');
  }
  return context;
};

// ═══════════════════════════════════════════════════════════════════════════
// PROVIDER
// ═══════════════════════════════════════════════════════════════════════════

export interface TerminalToastProviderProps {
  children: ReactNode;
  maxToasts?: number;
  defaultDuration?: number;
}

export const TerminalToastProvider: FC<TerminalToastProviderProps> = ({
  children,
  maxToasts = 5,
  defaultDuration = 5000,
}) => {
  const [toasts, setToasts] = useState<TerminalToast[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback(
    (message: string, variant: TerminalToastVariant, duration?: number): string => {
      const id = `terminal-toast-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
      const effectiveDuration = duration ?? (variant === 'loading' ? 0 : defaultDuration);
      const newToast: TerminalToast = {
        id,
        variant,
        message,
        timestamp: new Date(),
        duration: effectiveDuration,
      };

      setToasts((prev) => {
        const updated = [newToast, ...prev];
        return updated.slice(0, maxToasts);
      });

      // Auto-dismiss if duration > 0
      if (effectiveDuration > 0) {
        setTimeout(() => {
          removeToast(id);
        }, effectiveDuration);
      }

      return id;
    },
    [defaultDuration, maxToasts, removeToast]
  );

  const updateToast = useCallback((id: string, updates: Partial<Omit<TerminalToast, 'id'>>) => {
    setToasts((prev) =>
      prev.map((t) => (t.id === id ? { ...t, ...updates, timestamp: new Date() } : t))
    );
    // If updating to a non-loading variant, set up auto-dismiss
    if (updates.variant && updates.variant !== 'loading') {
      const duration = updates.duration ?? 3000;
      if (duration > 0) {
        setTimeout(() => {
          removeToast(id);
        }, duration);
      }
    }
  }, [removeToast]);

  const clearToasts = useCallback(() => {
    setToasts([]);
  }, []);

  // Convenience methods
  const success = useCallback(
    (message: string, duration?: number) => addToast(message, 'success', duration ?? 3000),
    [addToast]
  );
  const error = useCallback(
    (message: string, duration?: number) => addToast(message, 'error', duration ?? 5000),
    [addToast]
  );
  const warning = useCallback(
    (message: string, duration?: number) => addToast(message, 'warning', duration ?? 4000),
    [addToast]
  );
  const info = useCallback(
    (message: string, duration?: number) => addToast(message, 'info', duration ?? 3000),
    [addToast]
  );
  const loading = useCallback(
    (message: string) => addToast(message, 'loading', 0),
    [addToast]
  );

  return (
    <TerminalToastContext.Provider
      value={{
        toasts,
        addToast,
        updateToast,
        removeToast,
        clearToasts,
        success,
        error,
        warning,
        info,
        loading,
      }}
    >
      {children}
      <TerminalToastContainer toasts={toasts} onDismiss={removeToast} />
    </TerminalToastContext.Provider>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// CONTAINER
// ═══════════════════════════════════════════════════════════════════════════

interface TerminalToastContainerProps {
  toasts: TerminalToast[];
  onDismiss: (id: string) => void;
}

const TerminalToastContainer: FC<TerminalToastContainerProps> = ({ toasts, onDismiss }) => {
  return (
    <div
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none"
      role="region"
      aria-label="Terminal notifications"
    >
      <AnimatePresence mode="popLayout">
        {toasts.map((toast) => (
          <TerminalToastItem key={toast.id} toast={toast} onDismiss={() => onDismiss(toast.id)} />
        ))}
      </AnimatePresence>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// TOAST ITEM
// ═══════════════════════════════════════════════════════════════════════════

const variantConfig: Record<
  TerminalToastVariant,
  { borderColor: string; iconBg: string; icon: ReactNode }
> = {
  success: {
    borderColor: 'border-l-emerald-500',
    iconBg: 'bg-emerald-500/20 text-emerald-400',
    icon: <Check className="h-4 w-4" />,
  },
  error: {
    borderColor: 'border-l-red-500',
    iconBg: 'bg-red-500/20 text-red-400',
    icon: <XCircle className="h-4 w-4" />,
  },
  warning: {
    borderColor: 'border-l-amber-500',
    iconBg: 'bg-amber-500/20 text-amber-400',
    icon: <AlertTriangle className="h-4 w-4" />,
  },
  info: {
    borderColor: 'border-l-blue-500',
    iconBg: 'bg-blue-500/20 text-blue-400',
    icon: <Info className="h-4 w-4" />,
  },
  loading: {
    borderColor: 'border-l-cyan-500',
    iconBg: 'bg-cyan-500/20 text-cyan-400',
    icon: <Loader2 className="h-4 w-4 animate-spin" />,
  },
};

function formatTimestamp(date: Date): string {
  return date.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

interface TerminalToastItemProps {
  toast: TerminalToast;
  onDismiss: () => void;
}

const TerminalToastItem: FC<TerminalToastItemProps> = ({ toast, onDismiss }) => {
  const { borderColor, iconBg, icon } = variantConfig[toast.variant];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 50, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 100, scale: 0.95 }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      className={cn(
        'pointer-events-auto flex items-center gap-3 min-w-[320px] max-w-md',
        'rounded-lg border border-slate-700/50 border-l-4 shadow-xl',
        'bg-slate-900/95 backdrop-blur-sm px-4 py-3',
        borderColor
      )}
      role="alert"
    >
      {/* Icon */}
      <span className={cn('flex-shrink-0 rounded-md p-1.5', iconBg)}>{icon}</span>

      {/* Content: Timestamp + Message */}
      <div className="flex-1 min-w-0 flex items-baseline gap-3">
        <span className="flex-shrink-0 font-mono text-xs text-slate-500 tabular-nums">
          {formatTimestamp(toast.timestamp)}
        </span>
        <span className="font-mono text-sm text-slate-200 truncate">{toast.message}</span>
      </div>

      {/* Dismiss button (not for loading) */}
      {toast.variant !== 'loading' && (
        <button
          type="button"
          onClick={onDismiss}
          className="flex-shrink-0 rounded p-1 text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
          aria-label="Dismiss notification"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </motion.div>
  );
};

export default TerminalToastProvider;
