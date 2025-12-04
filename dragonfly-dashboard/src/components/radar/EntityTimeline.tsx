/**
 * EntityTimeline
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * A vertical timeline showing enforcement events for an entity or judgment.
 * Shows the complete lifecycle: judgment creation, job/asset discovery,
 * offers made/accepted, and packets sent.
 */
import React from 'react';
import {
  AlertCircle,
  Briefcase,
  Check,
  Clock,
  DollarSign,
  FileText,
  Gavel,
  Loader2,
  PiggyBank,
} from 'lucide-react';
import { Card, CardContent } from '../primitives';
import { cn } from '../../lib/tokens';
import { useTimeline, type TimelineEvent } from '../../hooks/useTimeline';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type { TimelineEvent };

export interface EntityTimelineProps {
  /** Entity UUID - if provided, fetches timeline for this entity */
  entityId?: string;
  /** Judgment ID - if provided (and no entityId), fetches timeline for this judgment */
  judgmentId?: number;
  /** Optional className for the container */
  className?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

const eventTypeConfig: Record<
  string,
  { icon: React.ElementType; color: string; bgColor: string }
> = {
  new_judgment: {
    icon: Gavel,
    color: 'text-blue-600 dark:text-blue-400',
    bgColor: 'bg-blue-100 dark:bg-blue-900/30',
  },
  job_found: {
    icon: Briefcase,
    color: 'text-green-600 dark:text-green-400',
    bgColor: 'bg-green-100 dark:bg-green-900/30',
  },
  asset_found: {
    icon: PiggyBank,
    color: 'text-purple-600 dark:text-purple-400',
    bgColor: 'bg-purple-100 dark:bg-purple-900/30',
  },
  offer_made: {
    icon: DollarSign,
    color: 'text-amber-600 dark:text-amber-400',
    bgColor: 'bg-amber-100 dark:bg-amber-900/30',
  },
  offer_accepted: {
    icon: Check,
    color: 'text-emerald-600 dark:text-emerald-400',
    bgColor: 'bg-emerald-100 dark:bg-emerald-900/30',
  },
  packet_sent: {
    icon: FileText,
    color: 'text-indigo-600 dark:text-indigo-400',
    bgColor: 'bg-indigo-100 dark:bg-indigo-900/30',
  },
};

const defaultConfig = {
  icon: Clock,
  color: 'text-gray-600 dark:text-gray-400',
  bgColor: 'bg-gray-100 dark:bg-gray-800',
};

function formatDate(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function formatTime(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

interface TimelineItemProps {
  event: TimelineEvent;
  isLast: boolean;
}

const TimelineItem: React.FC<TimelineItemProps> = ({ event, isLast }) => {
  const config = eventTypeConfig[event.event_type] || defaultConfig;
  const Icon = config.icon;

  return (
    <div className="relative flex gap-4">
      {/* Timeline connector line */}
      {!isLast && (
        <div
          className="absolute left-[17px] top-10 w-0.5 h-full -translate-x-1/2 bg-border"
          aria-hidden="true"
        />
      )}

      {/* Icon */}
      <div
        className={cn(
          'relative z-10 flex h-9 w-9 shrink-0 items-center justify-center rounded-full',
          config.bgColor
        )}
      >
        <Icon className={cn('h-4 w-4', config.color)} />
      </div>

      {/* Content */}
      <div className="flex-1 pb-6">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-medium text-foreground">{event.summary}</p>
          <time
            dateTime={event.created_at}
            className="text-xs text-muted-foreground whitespace-nowrap"
          >
            {formatDate(event.created_at)}
          </time>
        </div>
        <time
          dateTime={event.created_at}
          className="text-xs text-muted-foreground"
        >
          {formatTime(event.created_at)}
        </time>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export function EntityTimeline({
  entityId,
  judgmentId,
  className,
}: EntityTimelineProps) {
  const { events, isLoading, error } = useTimeline(entityId, judgmentId);

  // Loading state
  if (isLoading) {
    return (
      <Card className={className}>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-sm text-muted-foreground">
            Loading timeline...
          </span>
        </CardContent>
      </Card>
    );
  }

  // Error state
  if (error) {
    return (
      <Card className={className}>
        <CardContent className="flex items-center gap-2 py-6 text-destructive">
          <AlertCircle className="h-5 w-5" />
          <span className="text-sm">{error}</span>
        </CardContent>
      </Card>
    );
  }

  // Empty state
  if (events.length === 0) {
    return (
      <Card className={className}>
        <CardContent className="py-8 text-center">
          <Clock className="mx-auto h-8 w-8 text-muted-foreground/50" />
          <p className="mt-2 text-sm text-muted-foreground">
            No events yet for this defendant.
          </p>
          <p className="text-xs text-muted-foreground/70">
            Events will appear here as enforcement actions occur.
          </p>
        </CardContent>
      </Card>
    );
  }

  // Timeline
  return (
    <Card className={className}>
      <CardContent className="pt-4">
        <div className="space-y-0">
          {events.map((event, index) => (
            <TimelineItem
              key={event.id}
              event={event}
              isLast={index === events.length - 1}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export default EntityTimeline;
