/**
 * LiveFeedTicker - Real-Time Event Stream Display
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Stock ticker-style component showing real-time database events.
 * Displays new judgments, completed jobs, and generated packets as they occur.
 *
 * Features:
 *   - Horizontal scrolling animation (stock ticker style)
 *   - Green flash animation on new events
 *   - Connection status indicator
 *   - Auto-pauses on hover for readability
 *   - Compact design for AppShell footer
 *
 * Data Sources:
 *   - ops.job_queue (job completions)
 *   - public.judgments (new ingestions)
 *   - enforcement.draft_packets (packet generation)
 */
import { type FC, useState, useCallback, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Zap,
  FileText,
  DollarSign,
  AlertCircle,
  Radio,
  Pause,
  Play,
} from 'lucide-react';
import { cn } from '../lib/design-tokens';
import { useRealtimeSubscription } from '../hooks/useRealtimeSubscription';
import { supabaseClient, IS_DEMO_MODE } from '../lib/supabaseClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface LiveEvent {
  id: string;
  type: 'job' | 'judgment' | 'packet';
  message: string;
  amount?: number;
  timestamp: Date;
}

interface LiveFeedTickerProps {
  /** Maximum number of events to display */
  maxEvents?: number;
  /** Animation speed (pixels per second) */
  speed?: number;
  /** CSS class name */
  className?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

const MAX_EVENTS_DEFAULT = 20;
const TICKER_SPEED_DEFAULT = 50; // pixels per second
const FLASH_DURATION_MS = 2000;

// Demo events for development
const DEMO_EVENTS: LiveEvent[] = [
  {
    id: 'demo-1',
    type: 'judgment',
    message: 'New judgment: Smith v. ABC Corp',
    amount: 45000,
    timestamp: new Date(Date.now() - 30000),
  },
  {
    id: 'demo-2',
    type: 'job',
    message: 'Batch completed: 47 judgments ingested',
    timestamp: new Date(Date.now() - 60000),
  },
  {
    id: 'demo-3',
    type: 'packet',
    message: 'Packet generated: Wage garnishment',
    amount: 12500,
    timestamp: new Date(Date.now() - 90000),
  },
  {
    id: 'demo-4',
    type: 'judgment',
    message: 'New judgment: Johnson LLC Default',
    amount: 78000,
    timestamp: new Date(Date.now() - 120000),
  },
  {
    id: 'demo-5',
    type: 'job',
    message: 'Enrichment completed: 12 records updated',
    timestamp: new Date(Date.now() - 150000),
  },
];

// ═══════════════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

function formatAmount(amount: number): string {
  if (amount >= 1_000_000) {
    return `$${(amount / 1_000_000).toFixed(1)}M`;
  }
  if (amount >= 1_000) {
    return `$${(amount / 1_000).toFixed(0)}K`;
  }
  return `$${amount.toFixed(0)}`;
}

function getEventIcon(type: LiveEvent['type']) {
  switch (type) {
    case 'judgment':
      return DollarSign;
    case 'job':
      return Zap;
    case 'packet':
      return FileText;
    default:
      return AlertCircle;
  }
}

function getEventColor(type: LiveEvent['type']) {
  switch (type) {
    case 'judgment':
      return 'text-emerald-400';
    case 'job':
      return 'text-cyan-400';
    case 'packet':
      return 'text-amber-400';
    default:
      return 'text-slate-400';
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const LiveFeedTicker: FC<LiveFeedTickerProps> = ({
  maxEvents = MAX_EVENTS_DEFAULT,
  speed = TICKER_SPEED_DEFAULT,
  className,
}) => {
  const [events, setEvents] = useState<LiveEvent[]>(IS_DEMO_MODE ? DEMO_EVENTS : []);
  const [isPaused, setIsPaused] = useState(false);
  const [isFlashing, setIsFlashing] = useState(false);
  const flashTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [contentWidth, setContentWidth] = useState(0);

  // Measure content width for animation
  useEffect(() => {
    const updateWidths = () => {
      if (containerRef.current) {
        const content = containerRef.current.querySelector('[data-ticker-content]');
        if (content) {
          setContentWidth((content as HTMLElement).scrollWidth);
        }
      }
    };

    updateWidths();
    window.addEventListener('resize', updateWidths);
    return () => window.removeEventListener('resize', updateWidths);
  }, [events]);

  // Flash animation handler
  const triggerFlash = useCallback(() => {
    setIsFlashing(true);
    if (flashTimeoutRef.current) {
      clearTimeout(flashTimeoutRef.current);
    }
    flashTimeoutRef.current = setTimeout(() => {
      setIsFlashing(false);
    }, FLASH_DURATION_MS);
  }, []);

  // Cleanup
  useEffect(() => {
    return () => {
      if (flashTimeoutRef.current) {
        clearTimeout(flashTimeoutRef.current);
      }
    };
  }, []);

  // Add new event to the feed
  const addEvent = useCallback(
    (event: Omit<LiveEvent, 'id' | 'timestamp'>) => {
      const newEvent: LiveEvent = {
        ...event,
        id: `${event.type}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        timestamp: new Date(),
      };

      setEvents((prev) => {
        const updated = [newEvent, ...prev].slice(0, maxEvents);
        return updated;
      });

      triggerFlash();
    },
    [maxEvents, triggerFlash]
  );

  // ═══════════════════════════════════════════════════════════════════════════
  // REALTIME SUBSCRIPTIONS
  // ═══════════════════════════════════════════════════════════════════════════

  // Subscribe to job queue updates
  const jobRealtime = useRealtimeSubscription({
    table: 'job_queue',
    schema: 'ops',
    event: 'UPDATE',
    onUpdate: (payload) => {
      const job = payload.new as {
        status?: string;
        job_type?: string;
        payload?: { principal?: number };
      } | null;
      if (job?.status === 'completed') {
        addEvent({
          type: 'job',
          message: `Job completed: ${job.job_type ?? 'processing'}`,
          amount: job.payload?.principal,
        });
      }
    },
    enabled: !IS_DEMO_MODE,
  });

  // Subscribe to new judgments
  const judgmentRealtime = useRealtimeSubscription({
    table: 'judgments',
    schema: 'public',
    event: 'INSERT',
    onInsert: (payload) => {
      const judgment = payload.new as {
        defendant_name?: string;
        principal_amount?: number;
      } | null;
      addEvent({
        type: 'judgment',
        message: `New judgment: ${judgment?.defendant_name ?? 'Unknown'}`,
        amount: judgment?.principal_amount,
      });
    },
    enabled: !IS_DEMO_MODE,
  });

  // Subscribe to packet generation
  const packetRealtime = useRealtimeSubscription({
    table: 'draft_packets',
    schema: 'enforcement',
    event: 'INSERT',
    onInsert: (payload) => {
      const packet = payload.new as {
        strategy?: string;
        estimated_recovery?: number;
      } | null;
      addEvent({
        type: 'packet',
        message: `Packet generated: ${packet?.strategy ?? 'enforcement'}`,
        amount: packet?.estimated_recovery,
      });
    },
    enabled: !IS_DEMO_MODE,
  });

  // Load initial events from v_live_feed_events view
  useEffect(() => {
    if (IS_DEMO_MODE) return;

    const loadInitialEvents = async () => {
      try {
        const { data, error } = await supabaseClient
          .from('v_live_feed_events')
          .select('*')
          .limit(maxEvents);

        if (error) {
          console.warn('[LiveFeed] Failed to load initial events:', error);
          return;
        }

        if (data && data.length > 0) {
          const loadedEvents: LiveEvent[] = data.map((row) => ({
            id: `${row.event_type}-${row.event_id}`,
            type: row.event_type as LiveEvent['type'],
            message: row.message,
            amount: row.amount || undefined,
            timestamp: new Date(row.event_time),
          }));
          setEvents(loadedEvents);
        }
      } catch (err) {
        console.warn('[LiveFeed] Error loading events:', err);
      }
    };

    loadInitialEvents();
  }, [maxEvents]);

  const isConnected =
    jobRealtime.isConnected || judgmentRealtime.isConnected || packetRealtime.isConnected;

  // Calculate animation duration based on content width and speed
  const animationDuration = contentWidth > 0 ? contentWidth / speed : 30;

  if (events.length === 0) {
    return (
      <div
        className={cn(
          'flex items-center justify-center h-8 px-4',
          'bg-dragonfly-navy-950/50 border-t border-white/5',
          className
        )}
      >
        <span className="text-[11px] text-slate-600">Waiting for events...</span>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={cn(
        'relative overflow-hidden h-8',
        'bg-dragonfly-navy-950/80 border-t border-white/5',
        isFlashing && 'ring-1 ring-emerald-500/50 ring-inset',
        className
      )}
      onMouseEnter={() => setIsPaused(true)}
      onMouseLeave={() => setIsPaused(false)}
    >
      {/* Flash overlay */}
      <AnimatePresence>
        {isFlashing && (
          <motion.div
            className="absolute inset-0 bg-emerald-500/10 pointer-events-none z-10"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
          />
        )}
      </AnimatePresence>

      {/* Connection status indicator */}
      <div className="absolute left-0 top-0 bottom-0 flex items-center px-3 z-20 bg-gradient-to-r from-dragonfly-navy-950 via-dragonfly-navy-950/95 to-transparent w-24">
        <div className="flex items-center gap-1.5">
          <Radio
            className={cn(
              'h-3 w-3',
              isConnected ? 'text-emerald-400 animate-pulse' : 'text-slate-600'
            )}
          />
          <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wider">
            Live
          </span>
          {isPaused ? (
            <Pause className="h-3 w-3 text-slate-500" />
          ) : (
            <Play className="h-3 w-3 text-slate-500" />
          )}
        </div>
      </div>

      {/* Scrolling ticker content */}
      <motion.div
        data-ticker-content
        className="flex items-center h-full whitespace-nowrap pl-28"
        animate={{
          x: isPaused ? 0 : [-contentWidth, 0],
        }}
        transition={{
          x: {
            duration: animationDuration,
            repeat: Infinity,
            ease: 'linear',
          },
        }}
      >
        {/* Duplicate events for seamless loop */}
        {[...events, ...events].map((event, index) => {
          const Icon = getEventIcon(event.type);
          const colorClass = getEventColor(event.type);

          return (
            <div
              key={`${event.id}-${index}`}
              className="flex items-center gap-2 px-4 border-r border-white/5"
            >
              <Icon className={cn('h-3.5 w-3.5', colorClass)} />
              <span className="text-[11px] text-slate-300">{event.message}</span>
              {event.amount && event.amount > 0 && (
                <span className={cn('text-[11px] font-mono font-medium', colorClass)}>
                  {formatAmount(event.amount)}
                </span>
              )}
            </div>
          );
        })}
      </motion.div>

      {/* Right fade gradient */}
      <div className="absolute right-0 top-0 bottom-0 w-16 bg-gradient-to-l from-dragonfly-navy-950 to-transparent pointer-events-none z-20" />
    </div>
  );
};

export default LiveFeedTicker;
