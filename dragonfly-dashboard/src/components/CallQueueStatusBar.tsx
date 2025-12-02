
import { AlertCircle, Clock, Phone } from 'lucide-react';

interface CallQueueStatusBarProps {
  totalCalls: number;
  overdueCalls: number;
  dueTodayCalls: number;
  highPriorityCalls: number;
}

export function CallQueueStatusBar({
  totalCalls,
  overdueCalls,
  dueTodayCalls,
  highPriorityCalls,
}: CallQueueStatusBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-xl bg-slate-50 px-4 py-3">
      <div className="flex items-center gap-2 text-sm">
        <Phone className="h-4 w-4 text-slate-400" />
        <span className="font-medium text-slate-700">{totalCalls} in queue</span>
      </div>

      {overdueCalls > 0 && (
        <div className="flex items-center gap-1.5 rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700">
          <AlertCircle className="h-3.5 w-3.5" />
          {overdueCalls} overdue
        </div>
      )}

      {dueTodayCalls > 0 && (
        <div className="flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700">
          <Clock className="h-3.5 w-3.5" />
          {dueTodayCalls} due today
        </div>
      )}

      {highPriorityCalls > 0 && (
        <div className="flex items-center gap-1.5 rounded-full bg-violet-100 px-3 py-1 text-xs font-semibold text-violet-700">
          ⭐ {highPriorityCalls} high priority
        </div>
      )}

      {totalCalls === 0 && (
        <span className="text-sm text-slate-500">All caught up! No calls pending.</span>
      )}
    </div>
  );
}

export default CallQueueStatusBar;
