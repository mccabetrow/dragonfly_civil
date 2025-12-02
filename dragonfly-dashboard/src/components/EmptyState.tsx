import React from 'react';
import { Inbox } from 'lucide-react';

export interface EmptyStateProps {
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  className?: string;
}

const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  actionLabel,
  onAction,
  className = '',
}) => (
  <div
    className={[
      'flex flex-col items-center gap-3 rounded-2xl border border-slate-200/80 bg-white/60 px-6 py-10 text-center text-slate-600 shadow-sm',
      className,
    ].join(' ')}
  >
    <span className="rounded-2xl bg-slate-100 p-3 text-slate-500">
      <Inbox className="h-5 w-5" aria-hidden="true" />
    </span>
    <div>
      <p className="text-base font-semibold text-slate-900">{title}</p>
      {description ? <p className="mt-1 text-sm text-slate-600">{description}</p> : null}
    </div>
    {actionLabel && onAction ? (
      <button
        type="button"
        onClick={onAction}
        className="rounded-full border border-slate-200 bg-white px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-700 transition hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
      >
        {actionLabel}
      </button>
    ) : null}
  </div>
);

export default EmptyState;
