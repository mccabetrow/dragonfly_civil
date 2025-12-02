/**
 * OpsCallQueuePanel - Today's call queue with inline action buttons
 * 
 * Shows next-best-task and queue list. Designed for Mom's daily workflow.
 */
import type { FC } from 'react';
import { Phone, PhoneOff, MessageSquare, Clock, ChevronRight, User } from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import type { PlaintiffCallQueueRow } from '../../hooks/usePlaintiffCallQueue';

interface OpsCallQueuePanelProps {
  /** Queue items to display */
  items: PlaintiffCallQueueRow[];
  /** Currently selected item ID */
  selectedId?: string | null;
  /** Called when an item is selected */
  onSelect?: (item: PlaintiffCallQueueRow) => void;
  /** Called when quick action is triggered */
  onQuickAction?: (item: PlaintiffCallQueueRow, action: 'call' | 'skip' | 'voicemail') => void;
  /** Whether data is loading */
  isLoading?: boolean;
  /** Additional className */
  className?: string;
}

const STATUS_STYLES: Record<string, string> = {
  new: 'bg-blue-50 text-blue-700 border-blue-200',
  contacted: 'bg-amber-50 text-amber-700 border-amber-200',
  qualified: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  sent_agreement: 'bg-purple-50 text-purple-700 border-purple-200',
  signed: 'bg-green-50 text-green-700 border-green-200',
  lost: 'bg-slate-100 text-slate-600 border-slate-200',
  unknown: 'bg-slate-100 text-slate-500 border-slate-200',
};

const OpsCallQueuePanel: FC<OpsCallQueuePanelProps> = ({
  items,
  selectedId,
  onSelect,
  onQuickAction,
  isLoading,
  className,
}) => {
  if (isLoading) {
    return (
      <div className={cn('rounded-2xl border border-slate-200 bg-white p-6 shadow-sm', className)}>
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50">
            <Phone className="h-5 w-5 text-blue-600" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Today's Call Queue</h3>
            <p className="text-xs text-slate-500">Loading...</p>
          </div>
        </div>
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse rounded-xl bg-slate-100 h-16" />
          ))}
        </div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className={cn('rounded-2xl border border-slate-200 bg-white p-6 shadow-sm', className)}>
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100">
            <Phone className="h-5 w-5 text-slate-400" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Today's Call Queue</h3>
            <p className="text-xs text-slate-500">All caught up!</p>
          </div>
        </div>
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/50 p-8 text-center">
          <p className="text-sm font-medium text-slate-600">No calls scheduled for today</p>
          <p className="mt-1 text-xs text-slate-400">Check back later or review the cases page</p>
        </div>
      </div>
    );
  }

  const formatPhone = (phone: string | null) => {
    if (!phone) return '—';
    const cleaned = phone.replace(/\D/g, '');
    if (cleaned.length === 10) {
      return `(${cleaned.slice(0, 3)}) ${cleaned.slice(3, 6)}-${cleaned.slice(6)}`;
    }
    return phone;
  };

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  };

  return (
    <div className={cn('rounded-2xl border border-slate-200 bg-white shadow-sm', className)}>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50">
            <Phone className="h-5 w-5 text-blue-600" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Today's Call Queue</h3>
            <p className="text-xs text-slate-500">{items.length} plaintiff{items.length !== 1 ? 's' : ''} to contact</p>
          </div>
        </div>
        <span className="rounded-full bg-blue-100 px-3 py-1 text-xs font-semibold text-blue-700">
          {items.length}
        </span>
      </div>

      {/* Queue List */}
      <div className="divide-y divide-slate-100">
        {items.map((item, index) => {
          const isSelected = selectedId === item.plaintiffId;
          const isFirst = index === 0;
          
          return (
            <div
              key={item.plaintiffId}
              className={cn(
                'group relative px-6 py-4 transition-all duration-150',
                isSelected && 'bg-blue-50/60',
                !isSelected && 'hover:bg-slate-50',
                isFirst && 'bg-gradient-to-r from-blue-50/80 to-transparent',
                onSelect && 'cursor-pointer'
              )}
              onClick={() => onSelect?.(item)}
            >
              {/* First item badge */}
              {isFirst && (
                <div className="absolute -left-px top-0 bottom-0 w-1 rounded-r bg-blue-500" />
              )}

              <div className="flex items-start justify-between gap-4">
                {/* Left: Plaintiff info */}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-900 truncate">
                      {item.plaintiffName}
                    </span>
                    <span className={cn(
                      'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase border',
                      STATUS_STYLES[item.status] || STATUS_STYLES.unknown
                    )}>
                      {item.statusLabel}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                    <span className="flex items-center gap-1">
                      <User className="h-3 w-3" />
                      {item.firmName || 'No firm'}
                    </span>
                    <span className="font-medium text-slate-700">
                      {formatCurrency(item.totalJudgmentAmount)}
                    </span>
                    <span>
                      {item.caseCount} case{item.caseCount !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <div className="mt-2 flex items-center gap-1.5 text-sm">
                    <Phone className="h-3.5 w-3.5 text-slate-400" />
                    <span className="font-mono text-slate-700">{formatPhone(item.phone)}</span>
                  </div>
                </div>

                {/* Right: Quick actions */}
                <div className="flex shrink-0 items-center gap-1.5 opacity-0 transition-opacity group-hover:opacity-100">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onQuickAction?.(item, 'call');
                    }}
                    className="rounded-lg bg-emerald-500 p-2 text-white shadow-sm transition hover:bg-emerald-600"
                    title="Mark as reached"
                    aria-label={`Mark ${item.plaintiffName} as reached`}
                  >
                    <Phone className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onQuickAction?.(item, 'voicemail');
                    }}
                    className="rounded-lg bg-amber-500 p-2 text-white shadow-sm transition hover:bg-amber-600"
                    title="Left voicemail"
                    aria-label={`Log voicemail for ${item.plaintiffName}`}
                  >
                    <MessageSquare className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onQuickAction?.(item, 'skip');
                    }}
                    className="rounded-lg bg-slate-200 p-2 text-slate-600 shadow-sm transition hover:bg-slate-300"
                    title="Skip / No answer"
                    aria-label={`Skip ${item.plaintiffName}`}
                  >
                    <PhoneOff className="h-4 w-4" />
                  </button>
                </div>

                {/* Chevron */}
                <ChevronRight className={cn(
                  'h-5 w-5 shrink-0 text-slate-300 transition',
                  isSelected && 'text-blue-500'
                )} />
              </div>

              {/* Last call info */}
              {item.lastCallAttemptedAt && (
                <div className="mt-2 flex items-center gap-1.5 text-[11px] text-slate-400">
                  <Clock className="h-3 w-3" />
                  <span>
                    Last attempt: {new Date(item.lastCallAttemptedAt).toLocaleDateString()}
                    {item.lastCallOutcome && ` — ${item.lastCallOutcome}`}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default OpsCallQueuePanel;
