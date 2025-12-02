/**
 * ActionList - Priority action items display
 *
 * Shows prioritized list of next actions with:
 * - Clear action type indicators
 * - Case context (defendant, amount, tier)
 * - Due date/urgency highlighting
 * - Quick action buttons
 */

import { type FC } from 'react';
import {
  Phone,
  FileText,
  Mail,
  Calendar,
  AlertTriangle,
  CheckCircle2,
  Clock,
  ChevronRight,
  User,
  DollarSign,
} from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { Badge, TierBadge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Skeleton } from '../ui/Skeleton';
import { formatCurrency, formatRelativeTime } from '../../lib/utils/formatters';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type ActionType = 
  | 'call' 
  | 'file' 
  | 'email' 
  | 'review' 
  | 'follow_up' 
  | 'escalate'
  | 'foil';

export type ActionUrgency = 'low' | 'normal' | 'high' | 'overdue';

export interface ActionItem {
  /** Unique identifier */
  id: string;

  /** Type of action */
  type: ActionType;

  /** Action title/description */
  title: string;

  /** Associated case number */
  caseNumber?: string;

  /** Defendant name */
  defendant?: string;

  /** Judgment amount */
  amount?: number;

  /** Case tier */
  tier?: 'A' | 'B' | 'C';

  /** Due date */
  dueDate?: Date | string;

  /** Urgency level */
  urgency?: ActionUrgency;

  /** Whether the action is completed */
  completed?: boolean;

  /** Additional notes */
  notes?: string;
}

export interface ActionListProps {
  /** Title for the action list */
  title?: string;

  /** Description text */
  description?: string;

  /** List of action items */
  items: ActionItem[];

  /** Maximum items to show (with "see more" link) */
  maxItems?: number;

  /** Handler when action item is clicked */
  onItemClick?: (item: ActionItem) => void;

  /** Handler for "See all" link */
  onSeeAll?: () => void;

  /** Whether data is loading */
  loading?: boolean;

  /** Empty state message */
  emptyMessage?: string;

  /** Additional CSS classes */
  className?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// ACTION TYPE CONFIG
// ═══════════════════════════════════════════════════════════════════════════

const ACTION_CONFIG: Record<
  ActionType,
  { icon: typeof Phone; label: string; color: string }
> = {
  call: {
    icon: Phone,
    label: 'Call',
    color: 'bg-blue-100 text-blue-700',
  },
  file: {
    icon: FileText,
    label: 'File',
    color: 'bg-purple-100 text-purple-700',
  },
  email: {
    icon: Mail,
    label: 'Email',
    color: 'bg-cyan-100 text-cyan-700',
  },
  review: {
    icon: CheckCircle2,
    label: 'Review',
    color: 'bg-emerald-100 text-emerald-700',
  },
  follow_up: {
    icon: Calendar,
    label: 'Follow-up',
    color: 'bg-amber-100 text-amber-700',
  },
  escalate: {
    icon: AlertTriangle,
    label: 'Escalate',
    color: 'bg-red-100 text-red-700',
  },
  foil: {
    icon: FileText,
    label: 'FOIL',
    color: 'bg-indigo-100 text-indigo-700',
  },
};

const URGENCY_CONFIG: Record<ActionUrgency, { label: string; style: string }> = {
  low: { label: 'Low', style: 'text-slate-500' },
  normal: { label: 'Normal', style: 'text-slate-600' },
  high: { label: 'High', style: 'text-amber-600 font-medium' },
  overdue: { label: 'Overdue', style: 'text-red-600 font-semibold' },
};

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const ActionList: FC<ActionListProps> = ({
  title = 'Next Actions',
  description,
  items,
  maxItems = 5,
  onItemClick,
  onSeeAll,
  loading = false,
  emptyMessage = 'No pending actions',
  className,
}) => {
  const displayItems = items.slice(0, maxItems);
  const hasMore = items.length > maxItems;

  // Loading skeleton
  if (loading) {
    return (
      <Card className={className}>
        <CardHeader>
          <Skeleton className="h-6 w-32" />
        </CardHeader>
        <CardContent className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="h-10 w-10 rounded-lg" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-48" />
                <Skeleton className="h-3 w-32" />
              </div>
              <Skeleton className="h-8 w-20 rounded-lg" />
            </div>
          ))}
        </CardContent>
      </Card>
    );
  }

  // Empty state
  if (items.length === 0) {
    return (
      <Card className={className}>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100">
              <CheckCircle2 className="h-6 w-6 text-emerald-600" />
            </div>
            <p className="mt-3 text-sm font-medium text-slate-900">All caught up!</p>
            <p className="mt-1 text-sm text-slate-500">{emptyMessage}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>{title}</CardTitle>
          {description && (
            <p className="mt-1 text-sm text-slate-500">{description}</p>
          )}
        </div>
        <Badge variant="info">{items.length} pending</Badge>
      </CardHeader>

      <CardContent className="p-0">
        <ul className="divide-y divide-slate-100">
          {displayItems.map((item) => (
            <ActionListItem
              key={item.id}
              item={item}
              onClick={() => onItemClick?.(item)}
            />
          ))}
        </ul>

        {hasMore && onSeeAll && (
          <div className="border-t border-slate-100 p-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={onSeeAll}
              className="w-full justify-center"
            >
              See all {items.length} actions
              <ChevronRight className="ml-1 h-4 w-4" />
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// ACTION LIST ITEM
// ═══════════════════════════════════════════════════════════════════════════

interface ActionListItemProps {
  item: ActionItem;
  onClick?: () => void;
}

const ActionListItem: FC<ActionListItemProps> = ({ item, onClick }) => {
  const config = ACTION_CONFIG[item.type];
  const Icon = config.icon;
  const urgency = item.urgency ?? 'normal';
  const urgencyConfig = URGENCY_CONFIG[urgency];

  // Format due date
  const dueDateText = item.dueDate ? formatRelativeTime(item.dueDate) : null;

  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className={cn(
          'flex w-full items-center gap-4 px-5 py-4 text-left transition-colors',
          'hover:bg-slate-50 focus:bg-slate-50 focus:outline-none',
          item.completed && 'opacity-50'
        )}
      >
        {/* Action type icon */}
        <span
          className={cn(
            'flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg',
            config.color
          )}
        >
          <Icon className="h-5 w-5" />
        </span>

        {/* Content */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'truncate font-medium text-slate-900',
                item.completed && 'line-through'
              )}
            >
              {item.title}
            </span>
            {item.tier && <TierBadge tier={item.tier} size="sm" />}
          </div>

          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-500">
            {item.defendant && (
              <span className="flex items-center gap-1">
                <User className="h-3.5 w-3.5" />
                {item.defendant}
              </span>
            )}
            {item.caseNumber && (
              <span className="font-mono text-xs">{item.caseNumber}</span>
            )}
            {item.amount !== undefined && (
              <span className="flex items-center gap-1 font-medium text-slate-700">
                <DollarSign className="h-3.5 w-3.5" />
                {formatCurrency(item.amount)}
              </span>
            )}
          </div>
        </div>

        {/* Right side: Due date & urgency */}
        <div className="flex flex-shrink-0 flex-col items-end gap-1">
          {dueDateText && (
            <span
              className={cn(
                'flex items-center gap-1 text-xs',
                urgencyConfig.style
              )}
            >
              <Clock className="h-3 w-3" />
              {dueDateText}
            </span>
          )}
          <ChevronRight className="h-4 w-4 text-slate-400" />
        </div>
      </button>
    </li>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// COMPACT ACTION LIST (for sidebar or small areas)
// ═══════════════════════════════════════════════════════════════════════════

interface CompactActionListProps {
  items: ActionItem[];
  onItemClick?: (item: ActionItem) => void;
  className?: string;
}

export const CompactActionList: FC<CompactActionListProps> = ({
  items,
  onItemClick,
  className,
}) => {
  if (items.length === 0) return null;

  return (
    <ul className={cn('space-y-2', className)}>
      {items.map((item) => {
        const config = ACTION_CONFIG[item.type];
        const Icon = config.icon;

        return (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onItemClick?.(item)}
              className={cn(
                'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors',
                'hover:bg-slate-100 focus:bg-slate-100 focus:outline-none'
              )}
            >
              <Icon className="h-4 w-4 text-slate-500" />
              <span className="flex-1 truncate text-sm text-slate-700">
                {item.title}
              </span>
              {item.tier && <TierBadge tier={item.tier} size="sm" />}
            </button>
          </li>
        );
      })}
    </ul>
  );
};

export default ActionList;
