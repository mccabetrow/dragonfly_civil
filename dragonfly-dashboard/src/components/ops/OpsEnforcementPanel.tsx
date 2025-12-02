/**
 * OpsEnforcementPanel - Enforcement timeline showing recent activity
 * 
 * Displays pipeline status and recent enforcement actions.
 */
import type { FC } from 'react';
import { Activity, CheckCircle, Clock, AlertCircle, FileText, ChevronRight } from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import type { EnforcementPipelineRow, PipelineStage } from '../../hooks/useEnforcementPipeline';
import { STAGE_LABELS } from '../../hooks/useEnforcementPipeline';

interface OpsEnforcementPanelProps {
  /** Pipeline items to display */
  items: EnforcementPipelineRow[];
  /** Called when an item is clicked */
  onSelect?: (item: EnforcementPipelineRow) => void;
  /** Whether data is loading */
  isLoading?: boolean;
  /** Maximum items to show */
  maxItems?: number;
  /** Additional className */
  className?: string;
}

const STAGE_ICONS: Record<PipelineStage, typeof Activity> = {
  awaiting_enrichment: Clock,
  awaiting_action_plan: FileText,
  awaiting_signature: AlertCircle,
  actions_in_progress: Activity,
  actions_complete: CheckCircle,
  closed: CheckCircle,
  unknown: Clock,
};

const STAGE_COLORS: Record<PipelineStage, string> = {
  awaiting_enrichment: 'bg-slate-100 text-slate-600',
  awaiting_action_plan: 'bg-amber-100 text-amber-700',
  awaiting_signature: 'bg-red-100 text-red-700',
  actions_in_progress: 'bg-blue-100 text-blue-700',
  actions_complete: 'bg-emerald-100 text-emerald-700',
  closed: 'bg-slate-100 text-slate-600',
  unknown: 'bg-slate-100 text-slate-500',
};

const OpsEnforcementPanel: FC<OpsEnforcementPanelProps> = ({
  items,
  onSelect,
  isLoading,
  maxItems = 10,
  className,
}) => {
  const displayItems = items.slice(0, maxItems);

  if (isLoading) {
    return (
      <div className={cn('rounded-2xl border border-slate-200 bg-white p-6 shadow-sm', className)}>
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50">
            <Activity className="h-5 w-5 text-emerald-600" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Enforcement Pipeline</h3>
            <p className="text-xs text-slate-500">Loading...</p>
          </div>
        </div>
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse rounded-xl bg-slate-100 h-14" />
          ))}
        </div>
      </div>
    );
  }

  if (displayItems.length === 0) {
    return (
      <div className={cn('rounded-2xl border border-slate-200 bg-white p-6 shadow-sm', className)}>
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100">
            <Activity className="h-5 w-5 text-slate-400" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Enforcement Pipeline</h3>
            <p className="text-xs text-slate-500">No active items</p>
          </div>
        </div>
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/50 p-8 text-center">
          <p className="text-sm font-medium text-slate-600">Pipeline is empty</p>
          <p className="mt-1 text-xs text-slate-400">Cases with enforcement actions will appear here</p>
        </div>
      </div>
    );
  }

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  };

  // Group by stage for the summary
  const stageCounts = displayItems.reduce((acc, item) => {
    acc[item.pipelineStage] = (acc[item.pipelineStage] || 0) + 1;
    return acc;
  }, {} as Record<PipelineStage, number>);

  return (
    <div className={cn('rounded-2xl border border-slate-200 bg-white shadow-sm', className)}>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50">
            <Activity className="h-5 w-5 text-emerald-600" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Enforcement Pipeline</h3>
            <p className="text-xs text-slate-500">{items.length} judgment{items.length !== 1 ? 's' : ''} in progress</p>
          </div>
        </div>
      </div>

      {/* Stage summary pills */}
      <div className="flex flex-wrap gap-2 border-b border-slate-100 px-6 py-3 bg-slate-50/50">
        {Object.entries(stageCounts).map(([stage, count]) => {
          const StageIcon = STAGE_ICONS[stage as PipelineStage] || Clock;
          return (
            <span
              key={stage}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium',
                STAGE_COLORS[stage as PipelineStage]
              )}
            >
              <StageIcon className="h-3 w-3" />
              {count} {STAGE_LABELS[stage as PipelineStage]}
            </span>
          );
        })}
      </div>

      {/* Items list */}
      <div className="divide-y divide-slate-100 max-h-[400px] overflow-y-auto">
        {displayItems.map((item) => {
          const StageIcon = STAGE_ICONS[item.pipelineStage] || Clock;
          
          return (
            <div
              key={item.judgmentId}
              className={cn(
                'group flex items-center gap-4 px-6 py-3 transition-all duration-150 hover:bg-slate-50',
                onSelect && 'cursor-pointer'
              )}
              onClick={() => onSelect?.(item)}
            >
              {/* Stage icon */}
              <div className={cn(
                'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                STAGE_COLORS[item.pipelineStage]
              )}>
                <StageIcon className="h-4 w-4" />
              </div>

              {/* Info */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-900 truncate text-sm">
                    {item.debtorName}
                  </span>
                  <span className="text-xs text-slate-400 font-mono">
                    {item.caseIndexNumber}
                  </span>
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
                  <span className="font-medium text-slate-700">
                    {formatCurrency(item.principalAmount)}
                  </span>
                  <span>•</span>
                  <span>{STAGE_LABELS[item.pipelineStage]}</span>
                  {item.totalActions > 0 && (
                    <>
                      <span>•</span>
                      <span>{item.completedActions}/{item.totalActions} actions</span>
                    </>
                  )}
                </div>
              </div>

              {/* Chevron */}
              <ChevronRight className="h-4 w-4 shrink-0 text-slate-300 opacity-0 transition group-hover:opacity-100" />
            </div>
          );
        })}
      </div>

      {/* Show more */}
      {items.length > maxItems && (
        <div className="border-t border-slate-100 px-6 py-3 text-center">
          <button
            type="button"
            className="text-sm font-medium text-blue-600 hover:text-blue-700"
          >
            View all {items.length} judgments →
          </button>
        </div>
      )}
    </div>
  );
};

export default OpsEnforcementPanel;
